"""Podcast generation service.

Generates conversational study podcasts from course materials by:
1. Fetching relevant content for a topic
2. Using LLM to generate a tutor-student dialogue script
3. Synthesizing each line with different TTS voices
4. Concatenating audio into a single MP3 podcast

Inspired by Podcastfy but implemented with OpenAI APIs for simplicity.
"""

import io
import json
import logging
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from services.audio.synthesis import get_tts_service, Voice

logger = logging.getLogger(__name__)

PodcastStyle = Literal["review", "deep_dive", "exam_prep"]

# Voice assignments for dialogue roles
TUTOR_VOICE: Voice = "onyx"
STUDENT_VOICE: Voice = "nova"

DIALOGUE_GENERATION_PROMPT = """You are a podcast script writer for an educational study podcast.

Given the following course material, generate a natural, engaging dialogue between:
- TUTOR: A knowledgeable, friendly tutor who explains concepts clearly
- STUDENT: A curious student who asks good questions and sometimes struggles

STYLE: {style_description}

Rules:
1. Generate 8-12 dialogue turns (alternating TUTOR/STUDENT)
2. Cover the key concepts from the material
3. Include at least one real-world example or analogy
4. The student should ask clarifying questions
5. End with a brief summary of key takeaways
6. Keep each line under 200 words for natural speech

Output format (JSON array):
[
  {{"role": "tutor", "text": "Welcome to our study session! Today we're going to..."}},
  {{"role": "student", "text": "That sounds interesting! I've been wondering about..."}},
  ...
]

Output ONLY the JSON array, no other text."""

STYLE_DESCRIPTIONS = {
    "review": "A quick review session hitting the main points. Keep it concise and focused on reinforcement.",
    "deep_dive": "An in-depth exploration of the topic. Go deeper into why things work, edge cases, and connections.",
    "exam_prep": "Exam preparation focus. Cover likely exam questions, common mistakes, and memory aids.",
}


async def generate_study_podcast(
    course_id: str,
    topic: str,
    db: AsyncSession,
    style: PodcastStyle = "review",
) -> tuple[bytes, list[dict]]:
    """Generate a study podcast for a given topic.

    Args:
        course_id: The course to source materials from.
        topic: The topic to cover in the podcast.
        db: Database session.
        style: Podcast style (review, deep_dive, exam_prep).

    Returns:
        Tuple of (mp3_audio_bytes, dialogue_script).
    """
    # 1. Fetch course content for the topic
    materials = await _fetch_topic_materials(course_id, topic, db)

    # 2. Generate dialogue script via LLM
    dialogue = await _generate_dialogue(materials, topic, style)

    # 3. Synthesize each line with appropriate voice
    tts = get_tts_service()
    audio_segments: list[bytes] = []

    for i, line in enumerate(dialogue):
        role = line.get("role", "tutor")
        text = line.get("text", "")
        if not text.strip():
            continue

        voice = TUTOR_VOICE if role == "tutor" else STUDENT_VOICE
        try:
            audio = await tts.synthesize(text, voice=voice, speed=1.0)
            audio_segments.append(audio)
            logger.debug("Synthesized line %d/%d (%s, %d bytes)", i + 1, len(dialogue), role, len(audio))
        except Exception as e:
            logger.error("TTS failed for line %d: %s", i, e)
            continue

    # 4. Concatenate MP3 segments
    # Simple concatenation works for MP3 (frames are independent)
    combined = b"".join(audio_segments)

    logger.info(
        "Generated podcast: topic=%s, style=%s, lines=%d, size=%d bytes",
        topic, style, len(dialogue), len(combined),
    )
    return combined, dialogue


async def _fetch_topic_materials(course_id: str, topic: str, db: AsyncSession) -> str:
    """Fetch course materials relevant to the topic."""
    try:
        from services.search.hybrid import hybrid_search
        import uuid

        results = await hybrid_search(
            query=topic,
            course_id=uuid.UUID(course_id),
            db=db,
            limit=5,
        )
        if results:
            return "\n\n---\n\n".join(
                f"## {r.get('title', 'Untitled')}\n{r.get('content', '')}"
                for r in results
            )
    except Exception as e:
        logger.warning("Failed to fetch materials for podcast: %s", e)

    return f"Topic: {topic}\n(No specific course materials found — generate general educational content)"


async def _generate_dialogue(materials: str, topic: str, style: PodcastStyle) -> list[dict]:
    """Use LLM to generate a dialogue script."""
    from services.llm.router import get_llm_client

    client = get_llm_client("small")

    system_prompt = DIALOGUE_GENERATION_PROMPT.format(
        style_description=STYLE_DESCRIPTIONS.get(style, STYLE_DESCRIPTIONS["review"]),
    )

    user_message = f"Topic: {topic}\n\nCourse Materials:\n{materials[:6000]}"

    try:
        response_text, _ = await client.chat(system_prompt, user_message)
        # Parse JSON from response
        # Strip markdown code fences if present
        from libs.text_utils import strip_code_fences
        cleaned = strip_code_fences(response_text)

        dialogue = json.loads(cleaned)
        if isinstance(dialogue, list) and len(dialogue) > 0:
            return dialogue
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to parse dialogue script: %s", e)

    # Fallback: simple 4-turn dialogue
    return [
        {"role": "tutor", "text": f"Today we're going to review {topic}. Let's start with the key concepts."},
        {"role": "student", "text": f"I've been studying {topic} but some parts are still confusing. Can you help?"},
        {"role": "tutor", "text": "Of course! Let me break it down step by step."},
        {"role": "student", "text": "That makes much more sense now. Thanks for explaining it so clearly!"},
    ]
