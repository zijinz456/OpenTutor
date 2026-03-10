"""AI title summarization for content nodes with meaningless filenames."""

import logging
import re
import uuid

from sqlalchemy import select

from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


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
        if t.startswith(('•', '-', '\u2013', '\u2014')) and len(t) < 80:
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
                    logger.info("Renamed '%s' \u2192 '%s'", title, new_title)
            except (ConnectionError, TimeoutError) as e:
                logger.warning("AI title generation network error for '%s': %s", title, e)
            except (ValueError, RuntimeError) as e:
                logger.exception("AI title generation unexpected error for '%s'", title)

        await db.commit()

    logger.info("AI title summarization: %d nodes renamed", updated)
    return updated
