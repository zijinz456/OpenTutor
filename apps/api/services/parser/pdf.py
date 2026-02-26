"""PDF parsing service using Marker → Markdown → content tree.

Reference: PageIndex pattern (md_to_tree) for building hierarchical content tree.
Reference: Marker (VikParuchuri/marker) for PDF → Markdown conversion.
"""

import re
import uuid
import asyncio
from functools import partial

from models.content import CourseContentTree


def _marker_pdf_to_markdown(file_path: str) -> str:
    """Convert PDF to Markdown using Marker.

    Marker is CPU/GPU intensive, so we run it in a thread.
    """
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(file_path)
        return rendered.markdown
    except ImportError:
        # Fallback: if marker not installed, try basic extraction
        raise ImportError(
            "marker-pdf is required for PDF parsing. "
            "Install with: pip install marker-pdf"
        )


def _markdown_to_tree(
    markdown: str,
    course_id: uuid.UUID,
    source_file: str,
) -> list[CourseContentTree]:
    """Convert Markdown to content tree nodes (PageIndex pattern).

    Splits on headings (# ## ###) to build a hierarchical tree.
    Each heading becomes a node; content under it becomes the node's content.
    """
    lines = markdown.split("\n")
    nodes: list[CourseContentTree] = []

    # Stack for tracking hierarchy: [(level, node)]
    stack: list[tuple[int, CourseContentTree]] = []
    current_content_lines: list[str] = []
    order_counter: dict[str | None, int] = {}  # parent_id → counter

    def flush_content():
        if stack and current_content_lines:
            content = "\n".join(current_content_lines).strip()
            if content:
                stack[-1][1].content = content
        current_content_lines.clear()

    # Root node for the document
    root = CourseContentTree(
        course_id=course_id,
        parent_id=None,
        title=source_file,
        level=0,
        order_index=0,
        source_file=source_file,
        source_type="pdf",
    )
    nodes.append(root)
    stack.append((0, root))

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    for line in lines:
        match = heading_pattern.match(line)
        if match:
            flush_content()

            level = len(match.group(1))
            title = match.group(2).strip()

            # Pop stack until we find the parent (last node with lower level)
            while len(stack) > 1 and stack[-1][0] >= level:
                stack.pop()

            parent = stack[-1][1]
            parent_key = str(parent.id)
            order_counter[parent_key] = order_counter.get(parent_key, 0) + 1

            node = CourseContentTree(
                course_id=course_id,
                parent_id=parent.id,
                title=title,
                level=level,
                order_index=order_counter[parent_key],
                source_file=source_file,
                source_type="pdf",
            )
            nodes.append(node)
            stack.append((level, node))
        else:
            current_content_lines.append(line)

    flush_content()
    return nodes


async def parse_pdf_to_tree(
    file_path: str,
    course_id: uuid.UUID,
    source_file: str,
) -> list[CourseContentTree]:
    """Full pipeline: PDF → Marker → Markdown → content tree nodes."""
    loop = asyncio.get_event_loop()

    # Run Marker in a thread (it's CPU-intensive)
    markdown = await loop.run_in_executor(
        None, partial(_marker_pdf_to_markdown, file_path)
    )

    # Build content tree
    nodes = _markdown_to_tree(markdown, course_id, source_file)
    return nodes
