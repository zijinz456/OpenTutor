"""Webhook endpoints for multi-channel messaging (WhatsApp, iMessage, Telegram, Discord).

These endpoints receive inbound messages from external messaging platforms,
verify their authenticity, parse the payload, and dispatch the message
through the agent pipeline in a background task so we can return 200
immediately (required by most messaging platform webhook contracts).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query, Request, Response

from config import settings
from database import async_session

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WhatsApp Cloud API
# ---------------------------------------------------------------------------

@router.get("/whatsapp")
async def whatsapp_verify(
    request: Request,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> Response:
    """WhatsApp webhook verification challenge (GET).

    When you register a webhook URL with Meta, they send a GET request
    with ``hub.mode=subscribe``, ``hub.verify_token=<your_token>``, and
    ``hub.challenge=<random_string>``.  We must echo back the challenge
    if the verify token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verification succeeded")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed (bad token or mode)")
    return Response(content="Verification failed", status_code=403)


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    """Receive incoming WhatsApp messages (POST).

    1. Read raw body and verify HMAC-SHA256 signature.
    2. Parse the webhook payload into an IncomingMessage.
    3. Dispatch processing in a background task.
    4. Return 200 immediately (WhatsApp requires fast acknowledgement).
    """
    from services.channels.whatsapp import WhatsAppAdapter
    from services.channels.dispatcher import dispatch_message

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    adapter = WhatsAppAdapter()

    # Verify HMAC signature
    if not await adapter.verify_webhook(body, headers):
        logger.warning("WhatsApp webhook signature verification failed")
        # Still return 200 to avoid Meta retrying endlessly,
        # but do not process the message.
        return Response(status_code=200)

    # Parse the JSON payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("WhatsApp webhook: invalid JSON body")
        return Response(status_code=200)

    # Parse into an IncomingMessage (may be None for status updates)
    incoming = await adapter.parse_webhook(payload, headers)
    if incoming is None:
        # Not a user message (delivery receipt, status update, etc.)
        return Response(status_code=200)

    # Dispatch in background so we can ACK the webhook immediately
    asyncio.create_task(
        _dispatch_with_session(adapter, incoming),
        name=f"whatsapp-dispatch-{incoming.message_id}",
    )

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# iMessage via BlueBubbles
# ---------------------------------------------------------------------------

@router.post("/imessage")
async def imessage_webhook(request: Request) -> Response:
    """Receive incoming iMessage via BlueBubbles webhook (POST).

    1. Verify the shared secret header.
    2. Parse the BlueBubbles webhook payload.
    3. Dispatch processing in a background task.
    4. Return 200 immediately.
    """
    from services.channels.imessage import IMessageAdapter
    from services.channels.dispatcher import dispatch_message

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    adapter = IMessageAdapter()

    # Verify shared secret
    if not await adapter.verify_webhook(body, headers):
        logger.warning("iMessage webhook secret verification failed")
        return Response(status_code=401)

    # Parse the JSON payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("iMessage webhook: invalid JSON body")
        return Response(status_code=200)

    # Parse into an IncomingMessage
    incoming = await adapter.parse_webhook(payload, headers)
    if incoming is None:
        return Response(status_code=200)

    # Dispatch in background
    asyncio.create_task(
        _dispatch_with_session(adapter, incoming),
        name=f"imessage-dispatch-{incoming.message_id}",
    )

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Telegram Bot API
# ---------------------------------------------------------------------------

@router.post("/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive incoming Telegram bot updates (POST).

    1. Verify the webhook (Telegram relies on secret URL paths for auth).
    2. Parse the Update payload into an IncomingMessage.
    3. Dispatch processing in a background task.
    4. Return 200 immediately (Telegram expects fast acknowledgement).
    """
    from services.channels.telegram import TelegramAdapter
    from services.channels.dispatcher import dispatch_message

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    adapter = TelegramAdapter()

    # Verify webhook
    if not await adapter.verify_webhook(body, headers):
        logger.warning("Telegram webhook verification failed")
        return Response(status_code=200)

    # Parse the JSON payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("Telegram webhook: invalid JSON body")
        return Response(status_code=200)

    # Parse into an IncomingMessage
    incoming = await adapter.parse_webhook(payload, headers)
    if incoming is None:
        # Not a user message (inline query, callback, etc.)
        return Response(status_code=200)

    # Dispatch in background
    asyncio.create_task(
        _dispatch_with_session(adapter, incoming),
        name=f"telegram-dispatch-{incoming.message_id}",
    )

    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Discord Interactions
# ---------------------------------------------------------------------------

@router.post("/discord")
async def discord_webhook(request: Request) -> Response:
    """Handle incoming Discord interactions (POST).

    1. Verify Ed25519 signature.
    2. Handle PING (type 1) immediately with PONG.
    3. For slash commands, send a deferred response and dispatch processing.
    4. Follow up with the actual response via interaction webhook.
    """
    from fastapi.responses import JSONResponse
    from services.channels.discord import (
        DiscordAdapter,
        INTERACTION_PING,
        RESPONSE_PONG,
        RESPONSE_DEFERRED_CHANNEL_MESSAGE,
    )
    from services.channels.dispatcher import dispatch_message

    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    adapter = DiscordAdapter()

    # Verify Ed25519 signature
    if not await adapter.verify_webhook(body, headers):
        logger.warning("Discord webhook signature verification failed")
        return Response(status_code=401)

    # Parse the JSON payload
    try:
        payload = await request.json()
    except Exception:
        logger.error("Discord webhook: invalid JSON body")
        return Response(status_code=400)

    interaction_type = payload.get("type", 0)

    # PING — Discord health check (must respond with PONG immediately)
    if interaction_type == INTERACTION_PING:
        return JSONResponse(content={"type": RESPONSE_PONG})

    # Parse into an IncomingMessage
    incoming = await adapter.parse_webhook(payload, headers)
    if incoming is None:
        return Response(status_code=200)

    # For slash commands, we need to send a deferred response first
    # (Discord requires a response within 3 seconds)
    interaction_id = payload.get("id", "")
    interaction_token = payload.get("token", "")

    # Send deferred response immediately
    await adapter.send_interaction_response(
        interaction_id=interaction_id,
        interaction_token=interaction_token,
        content="",
        response_type=RESPONSE_DEFERRED_CHANNEL_MESSAGE,
    )

    # Dispatch processing in background, then follow up with the response
    asyncio.create_task(
        _dispatch_discord_interaction(
            adapter, incoming, interaction_id, interaction_token,
        ),
        name=f"discord-dispatch-{incoming.message_id}",
    )

    return Response(status_code=200)


async def _dispatch_discord_interaction(
    adapter,
    incoming,
    interaction_id: str,
    interaction_token: str,
) -> None:
    """Dispatch a Discord interaction through the agent pipeline.

    After processing, sends the response as a follow-up to the deferred
    interaction response.
    """
    from services.channels.dispatcher import dispatch_message
    from services.channels.formatter import format_for_channel

    try:
        async with async_session() as db:
            from services.channels.identity import resolve_or_create_user
            from services.channels.commands import parse_command, execute_command
            from services.agent.orchestrator import run_agent_turn

            # Resolve user
            user, binding = await resolve_or_create_user(
                db, incoming.channel_type, incoming.channel_id,
            )

            # Check for slash commands
            cmd = parse_command(incoming.text)
            if cmd is not None:
                response_text = await execute_command(cmd, user, binding, db)
                await db.commit()
            elif not binding.active_course_id:
                response_text = (
                    "Please set up a course on OpenTutor first, "
                    "then use `/switch` to select it."
                )
            else:
                # Run agent turn
                from services.channels.dispatcher import _load_channel_history

                history = await _load_channel_history(db, user.id, binding.active_course_id)
                ctx = await run_agent_turn(
                    user_id=user.id,
                    course_id=binding.active_course_id,
                    message=incoming.text,
                    db=db,
                    db_factory=async_session,
                    history=history,
                    scene=None,
                    post_process_inline=True,
                )
                response_text = ctx.response or "I couldn't process that. Please try again."

            # Format for Discord
            formatted = format_for_channel(response_text, "discord")

            # Send follow-up via webhook
            import httpx
            followup_url = (
                f"https://discord.com/api/v10/webhooks/"
                f"{settings.discord_application_id}/{interaction_token}/messages/@original"
            )
            async with httpx.AsyncClient(timeout=10) as client:
                await client.patch(
                    followup_url,
                    json={"content": formatted[:2000]},
                )

    except Exception as exc:
        logger.error(
            "Discord interaction dispatch failed: %s", exc, exc_info=True,
        )
        # Try to send error follow-up
        try:
            import httpx
            followup_url = (
                f"https://discord.com/api/v10/webhooks/"
                f"{settings.discord_application_id}/{interaction_token}/messages/@original"
            )
            async with httpx.AsyncClient(timeout=10) as client:
                await client.patch(
                    followup_url,
                    json={"content": "Sorry, I encountered an error processing your request."},
                )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _dispatch_with_session(adapter, incoming) -> None:
    """Run dispatch_message inside a fresh database session.

    Background tasks don't have access to the request-scoped DB session,
    so we create a new one from the session factory.
    """
    from services.channels.dispatcher import dispatch_message

    try:
        async with async_session() as db:
            await dispatch_message(
                adapter=adapter,
                incoming=incoming,
                db=db,
                db_factory=async_session,
            )
    except Exception as exc:
        logger.error(
            "Background dispatch failed for %s/%s: %s",
            incoming.channel_type,
            incoming.channel_id,
            exc,
            exc_info=True,
        )
