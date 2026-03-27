"""Canvas LMS file ingestion and topic linking.

- ingest_canvas_files: download and ingest files discovered via Canvas API
- link_pdfs_to_canvas_topics: reparent PDF nodes under Canvas module topics
"""

import asyncio
import logging
import re
import uuid

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def ingest_canvas_files(
    db_factory,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    file_urls: list[dict],
    session_name: str,
    canvas_domain: str,
) -> int:
    """Download and ingest Canvas files (PDFs, docs) discovered during deep extraction.

    Runs as a background task after the main course scrape completes.
    Each file is downloaded, then run through the ingestion pipeline.

    Returns number of files successfully ingested.
    """
    from pathlib import Path as _Path
    from services.ingestion.document_loader import download_canvas_file
    from services.ingestion.pipeline import run_ingestion_pipeline
    from config import settings

    ingested = 0
    failed_files: list[str] = []
    save_dir = getattr(settings, "upload_dir", "uploads")
    sem = asyncio.Semaphore(5)

    async def _ingest_one(file_info: dict) -> tuple[int, str | None]:
        async with sem:
            try:
                saved_path = await download_canvas_file(
                    file_info,
                    session_name=session_name,
                    target_domain=canvas_domain,
                    save_dir=save_dir,
                )
                if not saved_path:
                    fname = file_info.get("filename", "unknown")
                    logger.warning("Skipped Canvas file (download failed): %s", fname)
                    return (0, fname)

                file_bytes = _Path(saved_path).read_bytes()
                if len(file_bytes) < 100:
                    logger.debug("Skipped Canvas file (too small): %s", file_info.get("filename"))
                    return (0, None)

                filename = file_info.get("filename", "file.pdf")
                async with db_factory() as file_db:
                    job = await run_ingestion_pipeline(
                        db=file_db,
                        user_id=user_id,
                        file_path=saved_path,
                        filename=filename,
                        course_id=course_id,
                        file_bytes=file_bytes,
                    )
                    await file_db.commit()

                if job.status != "failed" and (job.nodes_created or 0) > 0:
                    logger.info("Ingested Canvas file: %s (%d nodes)", filename, job.nodes_created or 0)
                    return (1, None)
                else:
                    logger.debug("Canvas file ingestion produced no nodes: %s", filename)
                    return (0, None)

            except (IOError, OSError) as e:
                logger.warning("Canvas file I/O error for %s: %s", file_info.get("filename"), e)
                return (0, None)
            except (ValueError, RuntimeError, ConnectionError, TimeoutError):
                logger.exception("Unexpected error ingesting Canvas file %s", file_info.get("filename"))
                return (0, None)

    results = await asyncio.gather(*[_ingest_one(f) for f in file_urls])
    for count, failed in results:
        ingested += count
        if failed:
            failed_files.append(failed)

    if failed_files:
        logger.warning(
            "Canvas ingestion: %d file(s) failed to download: %s",
            len(failed_files), ", ".join(failed_files[:10])
        )
    logger.info("Canvas file ingestion complete: %d/%d files ingested", ingested, len(file_urls))
    return ingested


async def link_pdfs_to_canvas_topics(
    db_factory,
    course_id: uuid.UUID,
    file_urls: list[dict],
) -> int:
    """Phase 2: Reparent PDF root nodes under their matching Canvas topic nodes.

    Each file_url dict carries module_name + item_title metadata from Canvas.
    We find the content tree root node whose source_file matches the filename,
    then find/create a topic parent node matching module_name, and reparent.
    """
    from models.content import CourseContentTree

    linked = 0
    async with db_factory() as db:
        # Get all root nodes (parent_id IS NULL) for this course
        result = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.parent_id.is_(None),
            )
        )
        root_nodes = result.scalars().all()
        if not root_nodes:
            return 0

        # Build lookup: source_file -> root node
        root_by_source: dict[str, CourseContentTree] = {}
        for node in root_nodes:
            if node.source_file:
                root_by_source[node.source_file] = node

        # Cache for topic parent nodes (module_name -> node)
        topic_cache: dict[str, CourseContentTree] = {}

        # Get existing topic nodes -- search all url/canvas_module nodes in tree
        # (they may be nested under a "Modules" parent from HTML scraping)
        existing_topics = await db.execute(
            select(CourseContentTree).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.source_type.in_(["url", "canvas_module"]),
            )
        )
        for topic_node in existing_topics.scalars().all():
            # Prefer canvas_module over url when duplicate titles exist
            existing = topic_cache.get(topic_node.title)
            if existing is None or (
                existing.source_type != "canvas_module"
                and topic_node.source_type == "canvas_module"
            ):
                topic_cache[topic_node.title] = topic_node

        # Get max order_index for new topic nodes
        from sqlalchemy import func
        max_order = await db.execute(
            select(func.max(CourseContentTree.order_index)).where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.parent_id.is_(None),
            )
        )
        next_order = (max_order.scalar() or 0) + 1

        already_linked: set[uuid.UUID] = set()

        for file_info in file_urls:
            module_name = file_info.get("module_name")
            filename = file_info.get("filename", "")
            if not module_name:
                continue

            # Try multiple matching strategies
            matched_root = None

            # Strategy 1: exact source_file match
            matched_root = root_by_source.get(filename)

            # Strategy 2: fuzzy match on filename stem
            if not matched_root:
                fn_stem = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE).lower().strip()
                for source, node in root_by_source.items():
                    if node.id in already_linked:
                        continue
                    src_stem = re.sub(r'\.pdf$', '', source, flags=re.IGNORECASE).lower().strip()
                    if fn_stem and src_stem and (
                        fn_stem in src_stem
                        or src_stem in fn_stem
                        or (len(fn_stem) > 10 and fn_stem[:15] == src_stem[:15])
                    ):
                        matched_root = node
                        break

            if not matched_root or matched_root.parent_id is not None or matched_root.id in already_linked:
                continue
            already_linked.add(matched_root.id)

            # Find or create the topic parent node
            if module_name not in topic_cache:
                # Check DB for an existing node with same course_id, title,
                # and source_type to avoid duplicates on re-sync.
                existing_result = await db.execute(
                    select(CourseContentTree).where(
                        CourseContentTree.course_id == course_id,
                        CourseContentTree.title == module_name,
                        CourseContentTree.source_type == "canvas_module",
                    ).limit(1)
                )
                existing_node = existing_result.scalar_one_or_none()
                if existing_node is not None:
                    topic_cache[module_name] = existing_node
                else:
                    topic_node = CourseContentTree(
                        course_id=course_id,
                        title=module_name,
                        level=0,
                        order_index=next_order,
                        source_type="canvas_module",
                        source_file="canvas_structure",
                    )
                    db.add(topic_node)
                    await db.flush()
                    topic_cache[module_name] = topic_node
                    next_order += 1

            parent_node = topic_cache[module_name]
            matched_root.parent_id = parent_node.id
            matched_root.level = 1
            linked += 1
            logger.info("Linked PDF '%s' under topic '%s'", filename, module_name)

        await db.commit()

    logger.info("PDF-topic linking: %d/%d files linked", linked, len(file_urls))
    return linked
