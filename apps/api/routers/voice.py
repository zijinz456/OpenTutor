"""Voice endpoints: WebSocket voice session + podcast generation.

WebSocket protocol (JSON messages + binary audio):
  Client → Server:
    {"type": "audio", "data": "<base64>", "format": "webm"}
    {"type": "config", "tts_voice": "alloy", "language": "auto", "tts_enabled": true}
  Server → Client:
    {"type": "transcript", "text": "..."}
    {"type": "message", "content": "..."}  (text chunks from agent)
    {"type": "audio", "data": "<base64>"}  (TTS audio chunk, base64-encoded mp3)
    {"type": "status", "phase": "..."}
    {"type": "done", "metadata": {...}}
    {"type": "error", "message": "..."}
"""

import base64
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from config import settings
from database import get_db, async_session
from models.user import User
from services.audio.transcription import get_stt_service
from services.audio.synthesis import get_tts_service
from services.agent.orchestrator import orchestrate_stream
from services.auth.dependency import get_current_user
from services.auth.jwt import decode_token
from services.course_access import get_course_or_404
from services.llm.readiness import ensure_llm_ready

logger = logging.getLogger(__name__)

router = APIRouter()
ALLOWED_PODCAST_STYLES = {"review", "deep_dive", "exam_prep"}
ALLOWED_VOICES = {"alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"}


class PodcastRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200)
    style: str = "review"

    @field_validator("style")
    @classmethod
    def normalize_style(cls, value: str) -> str:
        return value if value in ALLOWED_PODCAST_STYLES else "review"


async def _get_or_create_single_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(name="Owner")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _resolve_voice_user(db: AsyncSession, ws: WebSocket) -> User:
    if settings.deployment_mode == "single_user" and not settings.auth_enabled:
        return await _get_or_create_single_user(db)

    token = ws.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Voice websocket requires an access token",
        )

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = uuid.UUID(payload["sub"])
    except HTTPException:
        raise
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


@router.websocket("/ws/{course_id}")
async def voice_session(ws: WebSocket, course_id: str):
    """WebSocket endpoint for voice-based chat sessions.

    Flow:
    1. Client sends audio bytes (base64-encoded in JSON)
    2. Server transcribes via OpenAI Whisper
    3. Server routes through orchestrate_stream() (same as text chat)
    4. Server streams back text + optional TTS audio
    """
    await ws.accept()

    stt = get_stt_service()
    tts = get_tts_service()

    # Session config (can be updated by client)
    config = {
        "tts_voice": "alloy",
        "tts_enabled": True,
        "language": None,  # auto-detect
        "speed": 1.0,
    }

    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError:
        await ws.send_text(json.dumps({"type": "error", "message": "Invalid course_id"}))
        await ws.close(code=1008, reason="Invalid course_id")
        return

    try:
        async with async_session() as db:
            user = await _resolve_voice_user(db, ws)
            await get_course_or_404(db, course_uuid, user_id=user.id)
            await ensure_llm_ready("Voice tutoring")
            user_id = user.id
    except HTTPException as exc:
        await ws.send_text(json.dumps({"type": "error", "message": exc.detail}))
        await ws.close(code=1008, reason=str(exc.detail))
        return
    except Exception as exc:
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await ws.close(code=1011, reason="LLM unavailable")
        return

    session_id: uuid.UUID | None = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = msg.get("type")

            if msg_type == "config":
                # Update session configuration
                if "tts_voice" in msg:
                    config["tts_voice"] = msg["tts_voice"]
                if "tts_enabled" in msg:
                    config["tts_enabled"] = bool(msg["tts_enabled"])
                if "language" in msg:
                    config["language"] = msg["language"] if msg["language"] != "auto" else None
                if "speed" in msg:
                    config["speed"] = max(0.25, min(4.0, float(msg["speed"])))
                continue

            if msg_type != "audio":
                await ws.send_text(json.dumps({"type": "error", "message": f"Unknown message type: {msg_type}"}))
                continue

            # Decode audio data
            audio_b64 = msg.get("data", "")
            audio_format = msg.get("format", "webm")
            try:
                audio_bytes = base64.b64decode(audio_b64)
            except Exception:
                await ws.send_text(json.dumps({"type": "error", "message": "Invalid base64 audio data"}))
                continue

            if len(audio_bytes) < 100:
                await ws.send_text(json.dumps({"type": "error", "message": "Audio too short"}))
                continue

            # 1. Transcribe
            await ws.send_text(json.dumps({"type": "status", "phase": "transcribing"}))
            try:
                result = await stt.transcribe(
                    audio_bytes,
                    language=config["language"],
                    filename=f"audio.{audio_format}",
                )
                transcript = result["text"]
            except Exception as e:
                logger.error("Voice STT failed: %s", e)
                await ws.send_text(json.dumps({"type": "error", "message": "Transcription failed"}))
                continue

            if not transcript.strip():
                await ws.send_text(json.dumps({"type": "error", "message": "No speech detected"}))
                continue

            # Send transcript back
            await ws.send_text(json.dumps({"type": "transcript", "text": transcript}))

            # 2. Route through orchestrator (same as text chat)
            await ws.send_text(json.dumps({"type": "status", "phase": "thinking"}))

            full_response = ""
            try:
                async with async_session() as db:
                    async for event in orchestrate_stream(
                        user_id=user_id,
                        course_id=course_uuid,
                        message=transcript,
                        db=db,
                        db_factory=async_session,
                        session_id=session_id,
                    ):
                        event_type = event.get("event", "")

                        if event_type == "message":
                            try:
                                payload = json.loads(event["data"])
                                content = payload.get("content", "")
                                if content:
                                    full_response += content
                                    await ws.send_text(json.dumps({
                                        "type": "message",
                                        "content": content,
                                    }))
                            except (json.JSONDecodeError, KeyError):
                                pass

                        elif event_type == "status":
                            await ws.send_text(json.dumps({
                                "type": "status",
                                "phase": json.loads(event.get("data", "{}")).get("phase", ""),
                            }))

                        elif event_type == "done":
                            try:
                                done_data = json.loads(event["data"])
                                session_id_str = done_data.get("session_id")
                                if session_id_str:
                                    session_id = uuid.UUID(session_id_str)
                            except (json.JSONDecodeError, KeyError, ValueError):
                                pass

            except Exception as e:
                logger.error("Voice orchestration failed: %s", e, exc_info=True)
                await ws.send_text(json.dumps({"type": "error", "message": "Processing failed"}))
                continue

            # 3. TTS synthesis
            if config["tts_enabled"] and full_response.strip():
                await ws.send_text(json.dumps({"type": "status", "phase": "speaking"}))
                try:
                    audio_data = await tts.synthesize(
                        full_response,
                        voice=config["tts_voice"],
                        speed=config["speed"],
                    )
                    # Send as base64-encoded JSON (avoids mixed binary/text WebSocket complexity)
                    await ws.send_text(json.dumps({
                        "type": "audio",
                        "data": base64.b64encode(audio_data).decode("ascii"),
                        "format": "mp3",
                    }))
                except Exception as e:
                    logger.error("Voice TTS failed: %s", e)
                    # Non-fatal: text was already sent

            # Done
            await ws.send_text(json.dumps({
                "type": "done",
                "metadata": {"session_id": str(session_id) if session_id else None},
            }))

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected for course %s", course_id)
    except Exception as e:
        logger.error("Voice WebSocket error: %s", e, exc_info=True)
        try:
            await ws.close(code=1011, reason="Internal error")
        except Exception:
            pass

@router.post("/synthesize")
async def synthesize_text(
    text: str,
    voice: str = "alloy",
    speed: float = 1.0,
    user=Depends(get_current_user),
):
    """REST endpoint to synthesize text to speech. Returns MP3 audio."""
    from fastapi import HTTPException

    if not text or len(text) > 4096:
        raise HTTPException(status_code=400, detail="Text must be 1-4096 characters")
    if voice not in ALLOWED_VOICES:
        raise HTTPException(status_code=400, detail=f"Voice must be one of: {', '.join(sorted(ALLOWED_VOICES))}")
    speed = max(0.25, min(4.0, speed))

    tts = get_tts_service()
    audio_bytes = await tts.synthesize(text, voice=voice, speed=speed)

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )


@router.post("/transcribe")
async def transcribe_audio(
    audio_data: str,  # base64-encoded
    language: str | None = None,
    audio_format: str = "webm",
    user=Depends(get_current_user),
):
    """REST endpoint to transcribe audio to text."""
    from fastapi import HTTPException

    try:
        audio_bytes = base64.b64decode(audio_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio data")

    if len(audio_bytes) < 100:
        raise HTTPException(status_code=400, detail="Audio data too short")

    stt = get_stt_service()
    result = await stt.transcribe(
        audio_bytes,
        language=language if language != "auto" else None,
        filename=f"audio.{audio_format}",
    )
    return result


@router.post("/podcast/{course_id}")
async def generate_podcast(
    course_id: uuid.UUID,
    body: PodcastRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate a study podcast for a course topic.

    Returns MP3 audio as a streaming response.
    """
    from services.audio.podcast_assets import generate_and_store_podcast

    await get_course_or_404(db, course_id, user_id=user.id)
    await ensure_llm_ready("Podcast generation")

    audio_bytes, dialogue, asset_id = await generate_and_store_podcast(
        db=db,
        user_id=user.id,
        course_id=course_id,
        topic=body.topic,
        style=body.style,
    )

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="podcast-{body.topic[:30]}.mp3"',
            "X-Podcast-Lines": str(len(dialogue)),
            "X-Podcast-Asset-Id": str(asset_id) if asset_id else "",
        },
    )


@router.post("/podcast/{course_id}/script")
async def generate_podcast_script(
    course_id: uuid.UUID,
    body: PodcastRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate only the podcast dialogue script (without audio synthesis).

    Useful for previewing the script before generating audio.
    """
    from services.audio.podcast import _fetch_topic_materials, _generate_dialogue

    await get_course_or_404(db, course_id, user_id=user.id)

    materials = await _fetch_topic_materials(str(course_id), body.topic, db)
    dialogue = await _generate_dialogue(materials, body.topic, body.style)

    return {"topic": body.topic, "style": body.style, "dialogue": dialogue}
