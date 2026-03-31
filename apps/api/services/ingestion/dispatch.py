"""Step 6: Dispatch extracted content to appropriate business tables.

Routes classified content into content_tree, assignments, or exam records,
then triggers deadline extraction and auto-generation of learning content.
"""

import logging

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import IngestionJob, Assignment

logger = logging.getLogger(__name__)


async def dispatch_content(db: AsyncSession, job: IngestionJob) -> dict:
    """Step 6: Dispatch extracted content to appropriate business tables."""
    result = {}

    if not job.course_id or not job.extracted_markdown:
        return result

    category = job.content_category or "other"
    source_name = (job.original_filename or "").lower()
    inferred_text_source = (
        source_name.endswith((".md", ".txt", ".rst", ".html", ".htm"))
        or (job.mime_type or "").startswith("text/")
        or job.source_type == "url"
    )

    if category in ("lecture_slides", "textbook", "notes", "syllabus") or (
        category == "other" and inferred_text_source
    ):
        # Build content tree using PageIndex pattern
        from services.parser.pdf import _markdown_to_tree
        from models.content import CourseContentTree
        source_label = job.original_filename or job.url or "Untitled"

        # Dedup: remove existing content tree nodes from the same source
        # before inserting new ones (prevents duplicates on re-ingestion)
        existing = await db.execute(
            select(CourseContentTree.id).where(
                CourseContentTree.course_id == job.course_id,
                CourseContentTree.source_file == source_label,
            )
        )
        old_ids = existing.scalars().all()
        if old_ids:
            from models.practice import PracticeProblem
            from sqlalchemy import delete as sa_delete

            # 1. Nullify FK references from practice_problems
            await db.execute(
                PracticeProblem.__table__.update()
                .where(PracticeProblem.content_node_id.in_(old_ids))
                .values(content_node_id=None)
            )
            # 2. Break self-referential parent_id chain (NO ACTION on delete):
            #    a) NULL out parent_id of the nodes being deleted
            await db.execute(
                CourseContentTree.__table__.update()
                .where(CourseContentTree.id.in_(old_ids))
                .values(parent_id=None)
            )
            #    b) NULL out parent_id of any OTHER node whose parent is being deleted
            await db.execute(
                CourseContentTree.__table__.update()
                .where(CourseContentTree.parent_id.in_(old_ids))
                .values(parent_id=None)
            )
            # 3. Bulk delete — all FK chains are now clear
            await db.execute(
                sa_delete(CourseContentTree).where(
                    CourseContentTree.id.in_(old_ids)
                )
            )
            await db.flush()
            logger.info("Dedup: removed %d existing nodes for source %s", len(old_ids), source_label)

        # PPT files: split per slide for precise search
        is_pptx = source_name.endswith((".pptx", ".ppt"))
        if is_pptx:
            import uuid as _uuid
            full_content = job.extracted_markdown.strip()
            slide_separator = "\n\n---\n\n"
            slide_chunks = [s.strip() for s in full_content.split(slide_separator) if s.strip()]

            root_summary = full_content[:500] + "..." if len(full_content) > 500 else full_content
            root = CourseContentTree(
                id=_uuid.uuid4(),
                course_id=job.course_id,
                parent_id=None,
                title=job.original_filename or "Presentation",
                level=0,
                order_index=0,
                content=root_summary,
                source_file=source_label,
                source_type=job.source_type,
            )
            nodes = [root]

            for i, slide_content in enumerate(slide_chunks):
                lines = slide_content.split("\n")
                title = lines[0].lstrip("#").strip() if lines else f"Slide {i + 1}"
                if not title or len(title) > 100:
                    title = f"Slide {i + 1}"
                child = CourseContentTree(
                    id=_uuid.uuid4(),
                    course_id=job.course_id,
                    parent_id=root.id,
                    title=title,
                    level=1,
                    order_index=i,
                    content=slide_content,
                    source_file=source_label,
                    source_type=job.source_type,
                )
                nodes.append(child)
            logger.info("PPT split into %d slide nodes for %s", len(slide_chunks), source_label)
        else:
            nodes = _markdown_to_tree(
                markdown=job.extracted_markdown,
                course_id=job.course_id,
                source_file=source_label,
            )
        for node in nodes:
            # Normalize source metadata to the ingestion source (file/url).
            node.source_type = job.source_type
            node.source_file = source_label
            node.content_category = category
            db.add(node)
        await db.flush()  # Assign IDs before indexing

        result["content_tree"] = len(nodes)

        # Queue auto-generation of learning content (notes, practice, flashcards)
        # Uses its own DB session to avoid sharing the caller's session across tasks.
        if nodes and job.course_id:
            from services.ingestion.auto_generation import _auto_generate_learning_content
            from database import async_session as async_session_factory
            import asyncio as _asyncio_dispatch

            async def _safe_auto_generate(course_id, user_id, node_data):
                """Run auto-generation with an independent DB session."""
                # Brief yield so the caller's transaction has time to commit
                # before we try to reference content_node_id FKs from a new session.
                await _asyncio_dispatch.sleep(1)
                try:
                    async with async_session_factory() as bg_db:
                        await _auto_generate_learning_content(bg_db, course_id, user_id, node_data)
                        await bg_db.commit()
                except (
                    sa.exc.SQLAlchemyError,
                    ConnectionError,
                    TimeoutError,
                    RuntimeError,
                    ValueError,
                    OSError,
                ):
                    logger.exception("Background auto-generation failed")

            from services.agent.background_runtime import track_background_task
            track_background_task(_asyncio_dispatch.create_task(
                _safe_auto_generate(job.course_id, job.user_id, nodes)
            ))

    elif category == "assignment":
        # Extract assignment info
        from services.ingestion.content_trimmer import trim_for_llm

        assignment = Assignment(
            course_id=job.course_id,
            title=job.original_filename or "Assignment",
            description=trim_for_llm(job.extracted_markdown, max_tokens=2000) if job.extracted_markdown else None,
            assignment_type="homework",
            source_ingestion_id=job.id,
        )
        db.add(assignment)
        result["assignments"] = 1

    elif category == "exam_schedule":
        from services.ingestion.content_trimmer import trim_for_llm

        assignment = Assignment(
            course_id=job.course_id,
            title=job.original_filename or "Exam",
            description=trim_for_llm(job.extracted_markdown, max_tokens=2000) if job.extracted_markdown else None,
            assignment_type="exam",
            source_ingestion_id=job.id,
        )
        db.add(assignment)
        result["assignments"] = 1

    # ── Cold-start layout (first document only) ──
    try:
        from models.course import Course
        from services.block_decision.cold_start import compute_cold_start_layout

        course_result = await db.execute(
            select(Course).where(Course.id == job.course_id)
        )
        course = course_result.scalar_one_or_none()
        if course:
            existing_meta = course.metadata_ or {}
            if not existing_meta.get("spaceLayout"):
                # Count LOOM concepts if available
                loom_count = 0
                try:
                    from models.progress import LearningProgress
                    count_result = await db.execute(
                        sa.select(sa.func.count(LearningProgress.id)).where(
                            LearningProgress.course_id == job.course_id
                        )
                    )
                    loom_count = count_result.scalar() or 0
                except (sa.exc.SQLAlchemyError, ImportError) as exc:
                    logger.debug("Could not count LOOM nodes for layout: %s", exc)
                cold_layout = compute_cold_start_layout(category, loom_count)
                course.metadata_ = {**existing_meta, "spaceLayout": cold_layout}
                result["cold_start_layout"] = True
    except (sa.exc.SQLAlchemyError, ImportError, ValueError) as e:
        logger.debug("Cold-start layout skipped: %s", e)

    # ── Automatic deadline extraction (all categories) ──
    if job.course_id and job.extracted_markdown:
        try:
            from services.ingestion.deadline_extractor import extract_and_create_deadlines
            canvas_assignments = getattr(job, "_canvas_assignments_data", None)
            deadline_count = await extract_and_create_deadlines(
                db=db,
                course_id=job.course_id,
                content=job.extracted_markdown,
                source_ingestion_id=job.id,
                canvas_assignments=canvas_assignments,
            )
            if deadline_count:
                result["deadlines_extracted"] = deadline_count
        except (sa.exc.SQLAlchemyError, ValueError, KeyError) as e:
            logger.warning("Deadline extraction failed (non-blocking): %s", e)
        except (RuntimeError, ConnectionError, TimeoutError) as e:
            logger.exception("Deadline extraction unexpected error (non-blocking)")

    return result
