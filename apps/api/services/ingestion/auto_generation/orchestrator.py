"""Orchestrator for full auto-preparation pipeline."""

import logging
import uuid

import sqlalchemy as sa

from services.ingestion.auto_generation.titles import auto_summarize_titles
from services.ingestion.auto_generation.notes import auto_generate_notes
from services.ingestion.auto_generation.practice import (
    auto_generate_flashcards,
    auto_generate_quiz,
)
from services.ingestion.auto_generation.configure import auto_configure_course

logger = logging.getLogger(__name__)


async def auto_prepare(
    db_factory,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    """Orchestrate full auto-preparation: notes + flashcards + quiz in parallel.

    Each step is independent -- one failure doesn't block the others.
    Runs all three concurrently for speed (30-second target).
    """
    import asyncio as _asyncio

    async def _safe_notes():
        try:
            return await auto_generate_notes(db_factory, course_id, user_id)
        except Exception as e:
            logger.exception("auto_prepare: notes step failed")
            return 0

    async def _safe_flashcards():
        try:
            return await auto_generate_flashcards(db_factory, course_id, user_id)
        except Exception as e:
            logger.exception("auto_prepare: flashcards step failed")
            return 0

    async def _safe_quiz():
        try:
            return await auto_generate_quiz(db_factory, course_id)
        except Exception as e:
            logger.exception("auto_prepare: quiz step failed")
            return 0

    results = await _asyncio.gather(
        _safe_notes(), _safe_flashcards(), _safe_quiz(),
        return_exceptions=True,
    )
    notes_count = results[0] if not isinstance(results[0], BaseException) else 0
    flashcards_count = results[1] if not isinstance(results[1], BaseException) else 0
    quiz_count = results[2] if not isinstance(results[2], BaseException) else 0
    summary: dict[str, int] = {
        "notes": notes_count,
        "flashcards": flashcards_count,
        "quiz": quiz_count,
    }

    # Auto-configure: analyze content -> select layout -> generate welcome message
    try:
        config = await auto_configure_course(db_factory, course_id, summary)
        summary["auto_configured"] = bool(config)
    except (sa.exc.SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError) as e:
        logger.exception("auto_prepare: auto-configure step failed")
        summary["auto_configured"] = False

    # LOOM: Build knowledge concept graph from content
    try:
        from services.loom import build_course_graph
        summary["loom_concepts"] = await build_course_graph(db_factory, course_id)
    except ImportError:
        logger.debug("LOOM module not available, skipping graph building")
        summary["loom_concepts"] = 0
    except (sa.exc.SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError) as e:
        logger.exception("auto_prepare: LOOM graph building failed")
        summary["loom_concepts"] = 0

    logger.info("auto_prepare complete for course %s: %s", course_id, summary)
    return summary
