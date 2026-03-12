"""Auto-generation functions extracted from pipeline.py.

Handles post-ingestion content generation:
- AI title summarization
- Notes, flashcards, quiz auto-generation
- Course auto-preparation orchestration
- Learning content generation (practice problems)

Auto-configuration extracted to auto_generation_config.py.
"""

import json
import logging
import re
import uuid

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.ingestion import IngestionJob, Assignment
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


async def auto_summarize_titles(db_factory, course_id: uuid.UUID) -> int:
    """Phase 3: Use AI to generate clean titles for content nodes with meaningless filenames."""
    from models.content import CourseContentTree

    def _is_meaningless_title(title: str) -> bool:
        t = title.strip()
        if not t:
            return True
        if re.match(
            r'^(\d+\.pdf|here\.+pdf|download\.pdf|file\.pdf|document\.pdf|'
            r'[a-f0-9]{8,}\.pdf|unnamed\.pdf|untitled\.pdf)$',
            t, re.IGNORECASE,
        ):
            return True
        if t.startswith(('•', '-', '–', '—')) and len(t) < 80:
            return True
        if re.match(r'^\d+\s', t) and len(t) < 30:
            return True
        return False

    updated = 0
    async with db_factory() as db:
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.level.in_([0, 1]),
            )
        )
        nodes = result.scalars().all()

        for node in nodes:
            title = node.title or ""
            if not _is_meaningless_title(title):
                continue
            content_preview = (node.content or "")[:500]
            if not content_preview:
                child_result = await db.execute(
                    select(CourseContentTree).where(
                        CourseContentTree.parent_id == node.id,
                        CourseContentTree.content.isnot(None),
                    ).limit(1)
                )
                child = child_result.scalar_one_or_none()
                if child:
                    content_preview = (child.content or "")[:500]
            if not content_preview or len(content_preview) < 30:
                continue
            try:
                client = get_llm_client("fast")
                prompt = (
                    f"Based on this document content, generate a short descriptive title "
                    f"(max 60 chars). Just output the title, nothing else.\n\n"
                    f"Original filename: {title}\n"
                    f"Content preview:\n{content_preview}"
                )
                new_title, _ = await client.extract(
                    "You are a document title generator. Output only the title.", prompt,
                )
                new_title = new_title.strip().strip('"\'')
                if new_title and 5 < len(new_title) < 100:
                    node.title = new_title
                    updated += 1
                    logger.info("Renamed '%s' -> '%s'", title, new_title)
            except (ConnectionError, TimeoutError) as e:
                logger.warning("AI title generation network error for '%s': %s", title, e)
            except (ValueError, RuntimeError) as e:
                logger.exception("AI title generation unexpected error for '%s'", title)
        await db.commit()
    logger.info("AI title summarization: %d nodes renamed", updated)
    return updated


async def auto_generate_notes(db_factory, course_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Phase 4: Auto-generate AI notes for content nodes after ingestion."""
    from models.content import CourseContentTree
    from services.parser.notes import restructure_notes
    from services.generated_assets import save_generated_asset
    import asyncio as _asyncio

    generated = 0
    async with db_factory() as db:
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.content.isnot(None),
            )
        )
        nodes = result.scalars().all()
        eligible = [n for n in nodes if n.content and len(n.content) > 200]
        if not eligible:
            return 0

        async def _gen_one(node):
            try:
                content_trimmed = node.content[:4000] if node.content else ""
                ai_content = await _asyncio.wait_for(
                    restructure_notes(content_trimmed, node.title, note_format="bullet_point"),
                    timeout=20,
                )
                if ai_content and len(ai_content) > 50:
                    return (node, ai_content)
            except _asyncio.TimeoutError:
                logger.warning("Auto-generate notes timed out for '%s'", node.title)
            except (ConnectionError, TimeoutError) as e:
                logger.warning("Auto-generate notes network error for '%s': %s", node.title, e)
            except (ValueError, RuntimeError) as e:
                logger.exception("Auto-generate notes unexpected error for '%s'", node.title)
            except Exception as e:
                logger.exception("Auto-generate notes failed for '%s'", node.title)
            return None

        results = await _asyncio.gather(*[_gen_one(n) for n in eligible[:5]], return_exceptions=True)
        for res in results:
            if isinstance(res, BaseException):
                logger.warning("Auto-generate gather returned exception: %s", res)
                continue
            if res:
                node, ai_content = res
                await save_generated_asset(
                    db, user_id=user_id, course_id=course_id,
                    asset_type="notes", title=node.title,
                    content={"markdown": ai_content},
                    metadata={"source_node_id": str(node.id), "auto_generated": True, "format": "bullet_point"},
                )
                generated += 1
                logger.info("Auto-generated notes for node '%s'", node.title)
        await db.commit()
    logger.info("Auto-generated notes: %d/%d nodes processed", generated, len(eligible))
    return generated


async def auto_generate_flashcards(db_factory, course_id: uuid.UUID, user_id: uuid.UUID, count: int = 10) -> int:
    """Auto-generate flashcards for a course after ingestion."""
    from services.generated_assets import save_generated_asset, list_generated_asset_batches

    async with db_factory() as db:
        existing = await list_generated_asset_batches(db, user_id=user_id, course_id=course_id, asset_type="flashcards")
        if existing:
            logger.info("Skipping auto-flashcards: %d batches already exist for course %s", len(existing), course_id)
            return 0
        try:
            from services.spaced_repetition.flashcards import generate_flashcards
            cards = await generate_flashcards(db, course_id, None, count)
            if not cards:
                return 0
            await save_generated_asset(
                db, user_id=user_id, course_id=course_id,
                asset_type="flashcards", title="Auto-generated starter set",
                content={"cards": cards}, metadata={"count": len(cards), "auto_generated": True},
            )
            await db.commit()
            logger.info("Auto-generated %d flashcards for course %s", len(cards), course_id)
            return len(cards)
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Auto flashcard generation network error for course %s: %s", course_id, e)
            return 0
        except (ValueError, RuntimeError, sa.exc.SQLAlchemyError, OSError) as exc:
            logger.exception("Auto flashcard generation failed for course %s", course_id)
            return 0


async def auto_generate_quiz(db_factory, course_id: uuid.UUID, question_count: int = 3) -> int:
    """Auto-generate quiz questions for a course after ingestion."""
    from models.content import CourseContentTree
    from models.practice import PracticeProblem
    from sqlalchemy import func as sa_func

    async with db_factory() as db:
        existing_count = (await db.execute(
            select(sa_func.count()).select_from(PracticeProblem).where(
                PracticeProblem.course_id == course_id,
                PracticeProblem.is_archived == False,  # noqa: E712
            )
        )).scalar() or 0
        if existing_count >= 3:
            logger.info("Skipping auto-quiz: %d questions already exist for course %s", existing_count, course_id)
            return 0
        try:
            from services.parser.quiz import extract_questions
            result = await db.execute(
                select(CourseContentTree).where(
                    CourseContentTree.course_id == course_id,
                    CourseContentTree.content.isnot(None),
                )
            )
            nodes = result.scalars().all()
            problems: list[PracticeProblem] = []
            for node in nodes[:3]:
                if node.content and len(node.content) > 100:
                    node_problems = await extract_questions(node.content, node.title, course_id, node.id)
                    problems.extend(node_problems)
                    if len(problems) >= question_count:
                        break
            added = 0
            for p in problems[:question_count]:
                db.add(p)
                added += 1
            await db.commit()
            logger.info("Auto-generated %d quiz questions for course %s", added, course_id)
            return added
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Auto quiz generation network error for course %s: %s", course_id, e)
            return 0
        except (ValueError, RuntimeError, sa.exc.SQLAlchemyError, OSError) as exc:
            logger.exception("Auto quiz generation failed for course %s", course_id)
            return 0


async def auto_prepare(db_factory, course_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """Orchestrate full auto-preparation: notes + flashcards + quiz in parallel."""
    import asyncio as _asyncio
    from services.ingestion.auto_generation_config import auto_configure_course

    async def _safe_notes():
        try:
            return await auto_generate_notes(db_factory, course_id, user_id)
        except (ConnectionError, TimeoutError, ValueError, RuntimeError, sa.exc.SQLAlchemyError, OSError):
            logger.exception("auto_prepare: notes step failed")
            return 0

    async def _safe_flashcards():
        try:
            return await auto_generate_flashcards(db_factory, course_id, user_id)
        except (ConnectionError, TimeoutError, ValueError, RuntimeError, sa.exc.SQLAlchemyError, OSError):
            logger.exception("auto_prepare: flashcards step failed")
            return 0

    async def _safe_quiz():
        try:
            return await auto_generate_quiz(db_factory, course_id)
        except (ConnectionError, TimeoutError, ValueError, RuntimeError, sa.exc.SQLAlchemyError, OSError):
            logger.exception("auto_prepare: quiz step failed")
            return 0

    notes_count, flashcards_count, quiz_count = await _asyncio.gather(
        _safe_notes(), _safe_flashcards(), _safe_quiz(),
    )
    summary: dict[str, int] = {"notes": notes_count, "flashcards": flashcards_count, "quiz": quiz_count}

    try:
        config = await auto_configure_course(db_factory, course_id, summary)
        summary["auto_configured"] = bool(config)
    except (sa.exc.SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError):
        logger.exception("auto_prepare: auto-configure step failed")
        summary["auto_configured"] = False

    try:
        from services.loom import build_course_graph
        summary["loom_concepts"] = await build_course_graph(db_factory, course_id)
    except ImportError:
        logger.debug("LOOM module not available, skipping graph building")
        summary["loom_concepts"] = 0
    except (sa.exc.SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, OSError):
        logger.exception("auto_prepare: LOOM graph building failed")
        summary["loom_concepts"] = 0

    logger.info("auto_prepare complete for course %s: %s", course_id, summary)
    return summary


async def _auto_generate_learning_content(
    db: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID, nodes: list,
) -> None:
    """Auto-generate practice problems and flashcards for newly ingested content nodes."""
    from models.practice import PracticeProblem

    eligible = [n for n in nodes if n.content and len(n.content) > 300]
    if not eligible:
        return

    for node in eligible[:20]:
        try:
            content_preview = (node.content or "")[:3000]
            if content_preview:
                client = get_llm_client("fast")
                prompt = (
                    f"Generate 2 multiple-choice practice problems from this content.\n"
                    f"Topic: {node.title}\n\nContent:\n{content_preview}\n\n"
                    f"For each problem provide: question, options (A/B/C/D), correct_answer, explanation.\n"
                    f"Format as JSON array."
                )
                raw, _ = await client.chat("You are a quiz generator. Output valid JSON arrays.", prompt)
                try:
                    json_start = raw.find("[")
                    json_end = raw.rfind("]") + 1
                    if json_start >= 0 and json_end > json_start:
                        problems = json.loads(raw[json_start:json_end])
                        for p in problems[:3]:
                            if not p.get("question"):
                                continue
                            options = p.get("options", {})
                            if isinstance(options, list):
                                options = {chr(65 + i): opt for i, opt in enumerate(options)}
                            problem = PracticeProblem(
                                course_id=course_id, content_node_id=node.id,
                                question_type="mc", question=p["question"],
                                options=options, correct_answer=p.get("correct_answer", "A"),
                                explanation=p.get("explanation", ""), difficulty_layer=1,
                                source="ai_generated", source_owner="ai", locked=False,
                            )
                            db.add(problem)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Failed to parse LLM response for auto-generation: %s", exc)
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Auto-generate learning content network error for '%s': %s", node.title, e)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Auto-generate learning content parse error for '%s': %s", node.title, e)
        except (RuntimeError, sa.exc.SQLAlchemyError, OSError) as e:
            logger.exception("Auto-generate learning content unexpected error for '%s'", node.title)

    try:
        await db.flush()
        logger.info("Auto-generated learning content for %d nodes in course %s", len(eligible), course_id)
    except (sa.exc.SQLAlchemyError, OSError):
        logger.exception("Failed to flush auto-generated content")


# Backward-compatible re-export
from services.ingestion.auto_generation_config import auto_configure_course  # noqa: E402, F401
