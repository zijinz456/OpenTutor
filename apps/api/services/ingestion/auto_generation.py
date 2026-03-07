"""Auto-generation functions extracted from pipeline.py.

Handles post-ingestion content generation:
- AI title summarization
- Notes, flashcards, quiz auto-generation
- Course auto-configuration (layout + welcome message)
- Learning content generation (practice problems)
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


# ---------------------------------------------------------------------------
# Layout presets (mirror frontend LAYOUT_PRESETS)
# ---------------------------------------------------------------------------

_LAYOUT_PRESETS = {
    "focused": {
        "preset": "focused",
        "sections": [
            {"type": "notes", "position": 0, "visible": False},
            {"type": "practice", "position": 1, "visible": False},
            {"type": "analytics", "position": 2, "visible": False},
            {"type": "plan", "position": 3, "visible": False},
        ],
        "chat_visible": True, "chat_height": 0.65,
        "tree_visible": True, "tree_width": 260,
    },
    "daily_study": {
        "preset": "daily_study",
        "sections": [
            {"type": "notes", "position": 0, "visible": True, "size": "large"},
            {"type": "practice", "position": 1, "visible": True, "size": "medium"},
            {"type": "analytics", "position": 2, "visible": False},
            {"type": "plan", "position": 3, "visible": False},
        ],
        "chat_visible": True, "chat_height": 0.35,
        "tree_visible": True, "tree_width": 240,
    },
    "exam_prep": {
        "preset": "exam_prep",
        "sections": [
            {"type": "notes", "position": 0, "visible": False},
            {"type": "practice", "position": 1, "visible": True, "size": "large"},
            {"type": "analytics", "position": 2, "visible": True, "size": "medium"},
            {"type": "plan", "position": 3, "visible": True, "size": "small"},
        ],
        "chat_visible": True, "chat_height": 0.25,
        "tree_visible": True, "tree_width": 200,
    },
    "assignment": {
        "preset": "assignment",
        "sections": [
            {"type": "notes", "position": 0, "visible": True, "size": "medium"},
            {"type": "practice", "position": 1, "visible": False},
            {"type": "analytics", "position": 2, "visible": False},
            {"type": "plan", "position": 3, "visible": True, "size": "large"},
        ],
        "chat_visible": True, "chat_height": 0.35,
        "tree_visible": True, "tree_width": 240,
    },
}


async def auto_summarize_titles(
    db_factory,
    course_id: uuid.UUID,
) -> int:
    """Phase 3: Use AI to generate clean titles for content nodes with meaningless filenames."""
    from models.content import CourseContentTree

    def _is_meaningless_title(title: str) -> bool:
        """Check if a title is meaningless and needs AI renaming."""
        t = title.strip()
        if not t:
            return True
        # Filename-like meaningless patterns
        if re.match(
            r'^(\d+\.pdf|here\.+pdf|download\.pdf|file\.pdf|document\.pdf|'
            r'[a-f0-9]{8,}\.pdf|unnamed\.pdf|untitled\.pdf)$',
            t, re.IGNORECASE,
        ):
            return True
        # Title is just a sentence fragment (starts with bullet, lowercase, or short number)
        if t.startswith(('•', '-', '–', '—')) and len(t) < 80:
            return True
        # Pure number titles
        if re.match(r'^\d+\s', t) and len(t) < 30:
            return True
        return False

    updated = 0
    async with db_factory() as db:
        # Get all root/level-0 nodes that might have bad titles
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

            # Get content preview: use node's own content or first child's content
            content_preview = (node.content or "")[:500]
            if not content_preview:
                # Try to get content from first child
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
                    "You are a document title generator. Output only the title.",
                    prompt,
                )
                new_title = new_title.strip().strip('"\'')
                if new_title and 5 < len(new_title) < 100:
                    node.title = new_title
                    updated += 1
                    logger.info("Renamed '%s' → '%s'", title, new_title)
            except Exception as e:
                logger.debug("AI title generation failed for '%s': %s", title, e)

        await db.commit()

    logger.info("AI title summarization: %d nodes renamed", updated)
    return updated


async def auto_generate_notes(
    db_factory,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """Phase 4: Auto-generate AI notes for content nodes after ingestion."""
    from models.content import CourseContentTree
    from services.parser.notes import restructure_notes
    from services.generated_assets import save_generated_asset

    generated = 0
    async with db_factory() as db:
        # Get content nodes with substantial content
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.content.isnot(None),
            )
        )
        nodes = result.scalars().all()

        # Filter to nodes with meaningful content (>200 chars)
        eligible = [n for n in nodes if n.content and len(n.content) > 200]
        if not eligible:
            return 0

        # Process top 5 nodes in parallel for speed (30s target)
        import asyncio as _asyncio

        async def _gen_one(node):
            try:
                content_trimmed = node.content[:4000] if node.content else ""
                ai_content = await _asyncio.wait_for(
                    restructure_notes(
                        content_trimmed,
                        node.title,
                        note_format="bullet_point",
                    ),
                    timeout=20,
                )
                if ai_content and len(ai_content) > 50:
                    return (node, ai_content)
            except Exception as e:
                logger.debug("Auto-generate notes failed for '%s': %s", node.title, e)
            return None

        results = await _asyncio.gather(*[_gen_one(n) for n in eligible[:5]])
        for res in results:
            if res:
                node, ai_content = res
                await save_generated_asset(
                    db,
                    user_id=user_id,
                    course_id=course_id,
                    asset_type="notes",
                    title=node.title,
                    content={"markdown": ai_content},
                    metadata={
                        "source_node_id": str(node.id),
                        "auto_generated": True,
                        "format": "bullet_point",
                    },
                )
                generated += 1
                logger.info("Auto-generated notes for node '%s'", node.title)

        await db.commit()

    logger.info("Auto-generated notes: %d/%d nodes processed", generated, len(eligible))
    return generated


async def auto_generate_flashcards(
    db_factory,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    count: int = 10,
) -> int:
    """Auto-generate flashcards for a course after ingestion.

    Dedup guard: skips if the course already has active flashcard assets.
    """
    from services.generated_assets import save_generated_asset, list_generated_asset_batches

    async with db_factory() as db:
        # Dedup guard — skip if flashcards already exist for this course
        existing = await list_generated_asset_batches(
            db, user_id=user_id, course_id=course_id, asset_type="flashcards",
        )
        if existing:
            logger.info("Skipping auto-flashcards: %d batches already exist for course %s", len(existing), course_id)
            return 0

        try:
            from services.spaced_repetition.flashcards import generate_flashcards
            cards = await generate_flashcards(db, course_id, None, count)
            if not cards:
                return 0

            await save_generated_asset(
                db,
                user_id=user_id,
                course_id=course_id,
                asset_type="flashcards",
                title="Auto-generated starter set",
                content={"cards": cards},
                metadata={"count": len(cards), "auto_generated": True},
            )
            await db.commit()
            logger.info("Auto-generated %d flashcards for course %s", len(cards), course_id)
            return len(cards)
        except Exception as e:
            logger.warning("Auto-generate flashcards failed: %s", e)
            return 0


async def auto_generate_quiz(
    db_factory,
    course_id: uuid.UUID,
    question_count: int = 3,
) -> int:
    """Auto-generate quiz questions for a course after ingestion.

    Dedup guard: skips if the course already has ≥3 active quiz questions.
    """
    from models.content import CourseContentTree
    from models.practice import PracticeProblem

    async with db_factory() as db:
        # Dedup guard — skip if enough quiz questions already exist
        from sqlalchemy import func as sa_func
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
                    node_problems = await extract_questions(
                        node.content, node.title, course_id, node.id,
                    )
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
        except Exception as e:
            logger.warning("Auto-generate quiz failed: %s", e)
            return 0


async def auto_prepare(
    db_factory,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict:
    """Orchestrate full auto-preparation: notes + flashcards + quiz in parallel.

    Each step is independent — one failure doesn't block the others.
    Runs all three concurrently for speed (30-second target).
    """
    import asyncio as _asyncio

    async def _safe_notes():
        try:
            return await auto_generate_notes(db_factory, course_id, user_id)
        except Exception as e:
            logger.warning("auto_prepare: notes step failed: %s", e)
            return 0

    async def _safe_flashcards():
        try:
            return await auto_generate_flashcards(db_factory, course_id, user_id)
        except Exception as e:
            logger.warning("auto_prepare: flashcards step failed: %s", e)
            return 0

    async def _safe_quiz():
        try:
            return await auto_generate_quiz(db_factory, course_id)
        except Exception as e:
            logger.warning("auto_prepare: quiz step failed: %s", e)
            return 0

    notes_count, flashcards_count, quiz_count = await _asyncio.gather(
        _safe_notes(), _safe_flashcards(), _safe_quiz(),
    )
    summary: dict[str, int] = {
        "notes": notes_count,
        "flashcards": flashcards_count,
        "quiz": quiz_count,
    }

    # Auto-configure: analyze content → select layout → generate welcome message
    try:
        config = await auto_configure_course(db_factory, course_id, summary)
        summary["auto_configured"] = bool(config)
    except Exception as e:
        logger.warning("auto_prepare: auto-configure step failed: %s", e)
        summary["auto_configured"] = False

    # LOOM: Build knowledge concept graph from content
    try:
        from services.loom import build_course_graph
        summary["loom_concepts"] = await build_course_graph(db_factory, course_id)
    except Exception as e:
        logger.warning("auto_prepare: LOOM graph building failed: %s", e)
        summary["loom_concepts"] = 0

    logger.info("auto_prepare complete for course %s: %s", course_id, summary)
    return summary


async def auto_configure_course(
    db_factory,
    course_id: uuid.UUID,
    prep_summary: dict,
) -> dict | None:
    """Analyze ingested course content and auto-configure layout + welcome message.

    Called after auto_prepare completes. Analyzes:
    - Assignment count & deadlines → assignment preset
    - Content categories (exam/quiz heavy) → exam_prep preset
    - Default → daily_study preset
    """
    from datetime import datetime, timezone
    from models.content import CourseContentTree

    async with db_factory() as db:
        # 1. Count assignments with deadlines
        assign_result = await db.execute(
            select(Assignment).where(Assignment.course_id == course_id)
        )
        assignments = assign_result.scalars().all()
        deadline_count = sum(1 for a in assignments if a.due_date)

        # 2. Check ingestion job content categories
        job_result = await db.execute(
            select(IngestionJob.content_category).where(
                IngestionJob.course_id == course_id,
                IngestionJob.content_category.isnot(None),
            )
        )
        categories = [r[0] for r in job_result.all()]

        # 3. Count content nodes
        node_result = await db.execute(
            select(sa.func.count()).select_from(CourseContentTree).where(
                CourseContentTree.course_id == course_id
            )
        )
        node_count = node_result.scalar() or 0

        # 4. Get course info
        course_result = await db.execute(
            select(Course).where(Course.id == course_id)
        )
        course = course_result.scalar_one_or_none()
        if not course:
            return None

        # --- Select layout preset ---
        exam_categories = {"exam_schedule", "assignment", "exam"}
        exam_cat_count = sum(1 for c in categories if c in exam_categories)

        if deadline_count >= 3:
            preset_id = "assignment"
        elif exam_cat_count >= 2 or (deadline_count >= 1 and exam_cat_count >= 1):
            preset_id = "exam_prep"
        else:
            preset_id = "focused"

        layout = _LAYOUT_PRESETS[preset_id]

        # --- Build welcome message ---
        now = datetime.now(timezone.utc)
        parts = [f"**{course.name}** is ready! Here's what I found:\n"]

        parts.append(f"- **{node_count}** content sections indexed")

        if prep_summary.get("notes", 0) > 0:
            parts.append(f"- **{prep_summary['notes']}** AI-generated note summaries")
        if prep_summary.get("flashcards", 0) > 0:
            parts.append(f"- **{prep_summary['flashcards']}** flashcards created")
        if prep_summary.get("quiz", 0) > 0:
            parts.append(f"- **{prep_summary['quiz']}** quiz questions generated")

        if deadline_count > 0:
            # Find the nearest upcoming deadline
            upcoming = [
                a for a in assignments
                if a.due_date and a.due_date > now
            ]
            upcoming.sort(key=lambda a: a.due_date)
            parts.append(f"- **{deadline_count}** deadlines detected")
            if upcoming:
                next_due = upcoming[0]
                days_left = (next_due.due_date - now).days
                parts.append(
                    f"- Next deadline: **{next_due.title}** in **{days_left} days**"
                )

        parts.append("")

        if preset_id == "assignment":
            parts.append(
                "I've set up your workspace in **Assignment Mode** with study plan "
                "and deadlines front and center. You can switch modes anytime by asking me."
            )
        elif preset_id == "exam_prep":
            parts.append(
                "I've set up your workspace in **Exam Prep Mode** with practice questions "
                "and analytics visible. Ask me to quiz you or review weak areas."
            )
        else:
            parts.append(
                "Your workspace is ready. "
                "Ask me anything about your materials — I'll explain, quiz you, or help you review."
            )

        welcome_message = "\n".join(parts)

        # --- Save to course metadata ---
        metadata = dict(course.metadata_ or {})
        metadata["layout"] = layout
        metadata["welcome_message"] = welcome_message
        metadata["auto_configured_at"] = now.isoformat()
        metadata["auto_config"] = {
            "preset": preset_id,
            "node_count": node_count,
            "deadline_count": deadline_count,
            "categories": categories[:20],
        }
        course.metadata_ = metadata
        await db.commit()

        logger.info(
            "Auto-configured course %s: preset=%s, nodes=%d, deadlines=%d",
            course_id, preset_id, node_count, deadline_count,
        )
        return {"preset": preset_id, "welcome_message": welcome_message}


async def _auto_generate_learning_content(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    nodes: list,
) -> None:
    """Auto-generate practice problems and flashcards for newly ingested content nodes.

    Runs as a fire-and-forget task after content tree creation.
    Only processes nodes with >300 chars of content.
    """
    from models.practice import PracticeProblem

    eligible = [n for n in nodes if n.content and len(n.content) > 300]
    if not eligible:
        return

    for node in eligible[:20]:  # Cap to avoid excessive processing
        try:
            # block_utils module removed — skip block conversion
            pass

            # Generate 2-3 practice problems per node
            content_preview = (node.content or "")[:3000]
            if content_preview:
                client = get_llm_client("fast")
                prompt = (
                    f"Generate 2 multiple-choice practice problems from this content.\n"
                    f"Topic: {node.title}\n\n"
                    f"Content:\n{content_preview}\n\n"
                    f"For each problem provide: question, options (A/B/C/D), correct_answer, explanation.\n"
                    f"Format as JSON array."
                )
                raw, _ = await client.chat(
                    "You are a quiz generator. Output valid JSON arrays.",
                    prompt,
                )

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
                                course_id=course_id,
                                content_node_id=node.id,
                                question_type="mc",
                                question=p["question"],
                                options=options,
                                correct_answer=p.get("correct_answer", "A"),
                                explanation=p.get("explanation", ""),
                                difficulty_layer=1,
                                source="ai_generated",
                                source_owner="ai",
                                locked=False,
                            )
                            db.add(problem)
                except (json.JSONDecodeError, ValueError):
                    pass

        except Exception as e:
            logger.debug("Auto-generate learning content failed for '%s': %s", node.title, e)

    try:
        await db.flush()
        logger.info("Auto-generated learning content for %d nodes in course %s", len(eligible), course_id)
    except Exception as e:
        logger.warning("Failed to flush auto-generated content: %s", e)
