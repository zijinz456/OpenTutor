"""Orchestrator for full auto-preparation pipeline."""

import logging
import uuid

import sqlalchemy as sa

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

    async def _safe_notes() -> tuple[int, str | None]:
        try:
            return (await auto_generate_notes(db_factory, course_id, user_id), None)
        except Exception as e:
            logger.exception("auto_prepare: notes step failed")
            return (0, str(e))

    async def _safe_flashcards() -> tuple[int, str | None]:
        try:
            return (await auto_generate_flashcards(db_factory, course_id, user_id), None)
        except Exception as e:
            logger.exception("auto_prepare: flashcards step failed")
            return (0, str(e))

    async def _safe_quiz() -> tuple[int, str | None]:
        try:
            return (await auto_generate_quiz(db_factory, course_id), None)
        except Exception as e:
            logger.exception("auto_prepare: quiz step failed")
            return (0, str(e))

    def _unpack(result) -> tuple[int, str | None]:
        if isinstance(result, BaseException):
            return (0, f"Unexpected: {result}")
        return result

    results = await _asyncio.gather(
        _safe_notes(), _safe_flashcards(), _safe_quiz(),
        return_exceptions=True,
    )
    n_count, n_err = _unpack(results[0])
    f_count, f_err = _unpack(results[1])
    q_count, q_err = _unpack(results[2])
    summary: dict = {
        "notes": n_count,
        "flashcards": f_count,
        "quiz": q_count,
    }
    errors: dict[str, str] = {}
    if n_err:
        errors["notes"] = n_err
    if f_err:
        errors["flashcards"] = f_err
    if q_err:
        errors["quiz"] = q_err
    if errors:
        summary["errors"] = errors

    # Auto-configure: analyze content -> select layout -> generate welcome message
    try:
        config = await auto_configure_course(db_factory, course_id, summary)
        summary["auto_configured"] = bool(config)
    except (sa.exc.SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError):
        logger.exception("auto_prepare: auto-configure step failed")
        summary["auto_configured"] = False

    # LOOM: Build knowledge concept graph from content
    try:
        from services.loom_graph import build_course_graph
        summary["loom_concepts"] = await build_course_graph(db_factory, course_id)
    except ImportError:
        logger.debug("LOOM module not available, skipping graph building")
        summary["loom_concepts"] = 0
    except (sa.exc.SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError):
        logger.exception("auto_prepare: LOOM graph building failed")
        summary["loom_concepts"] = 0

    logger.info("auto_prepare complete for course %s: %s", course_id, summary)
    return summary
