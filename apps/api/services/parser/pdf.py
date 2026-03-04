"""PDF parsing service using Marker → Markdown → content tree.

Enhanced with:
- Code-block-aware heading extraction (PageIndex pattern)
- Token counting with bottom-up accumulation (PageIndex)
- Tree thinning: merge small nodes into parents (PageIndex)
- No-heading fallback: paragraph splitting (Deep-Research separator pattern)

References:
- PageIndex: page_index_md.py extract_nodes_from_markdown(), tree_thinning_for_index()
- Deep-Research: text-splitter.ts recursive separators
- Marker (VikParuchuri/marker) for PDF → Markdown conversion
"""

import logging
import re
import uuid
import asyncio
from functools import partial

from models.content import CourseContentTree

logger = logging.getLogger(__name__)

# Tree thinning threshold (nodes with fewer total tokens get merged into parent)
MIN_NODE_TOKENS = 50

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")
CODE_BLOCK_PATTERN = re.compile(r"^```")


def _sanitize_title(title: str) -> str:
    """Strip newlines, collapse whitespace, and truncate titles."""
    title = title.replace("\n", " ").replace("\r", " ")
    title = re.sub(r"\s{2,}", " ", title).strip()
    return title[:120] if title else "Untitled"

# Marker model singleton — avoids reloading ~1GB models on every call
_marker_models: dict | None = None


def _get_marker_models() -> dict:
    """Lazy-load and cache Marker models as a module-level singleton."""
    global _marker_models
    if _marker_models is None:
        from marker.models import create_model_dict

        logger.info("Loading Marker models (one-time)...")
        _marker_models = create_model_dict()
    return _marker_models


def _marker_pdf_to_markdown(file_path: str) -> str:
    """Convert PDF to Markdown using Marker.

    Marker is CPU/GPU intensive, so we run it in a thread.
    Models are cached as a singleton to avoid repeated loading.
    """
    try:
        from marker.converters.pdf import PdfConverter

        models = _get_marker_models()
        converter = PdfConverter(artifact_dict=models)
        rendered = converter(file_path)
        return rendered.markdown
    except ImportError:
        raise ImportError(
            "marker-pdf is required for PDF parsing. "
            "Install with: pip install marker-pdf"
        )


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken (cl100k_base). Falls back to word-count estimate."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        # ~0.75 tokens per word estimate
        return max(1, int(len(text.split()) * 0.75))


def _has_headings_code_aware(markdown: str) -> bool:
    """Quick check if Markdown contains any headings outside code blocks.

    Stops at the first heading found — avoids scanning the entire document
    just to decide between heading-based vs paragraph-based tree building.
    """
    in_code_block = False

    for line in markdown.split("\n"):
        stripped = line.strip()
        if CODE_BLOCK_PATTERN.match(stripped):
            in_code_block = not in_code_block
            continue
        if not in_code_block and HEADING_PATTERN.match(line):
            return True
    return False


def _split_into_paragraphs(text: str, max_tokens: int = 500) -> list[dict]:
    """Split text without headings into paragraph-based nodes.

    Uses Deep-Research separator priority: \\n\\n > \\n > ". " > " "
    """
    # First split by double newlines (paragraph boundaries)
    paragraphs = text.split("\n\n")
    nodes = []
    current_chunk = []
    current_tokens = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_tokens = _count_tokens(para)

        if current_tokens + para_tokens > max_tokens and current_chunk:
            nodes.append({
                "title": _sanitize_title(current_chunk[0][:80]),
                "text": "\n\n".join(current_chunk),
                "level": 1,
            })
            current_chunk = []
            current_tokens = 0

        current_chunk.append(para)
        current_tokens += para_tokens

    if current_chunk:
        nodes.append({
            "title": _sanitize_title(current_chunk[0][:80]),
            "text": "\n\n".join(current_chunk),
            "level": 1,
        })

    return nodes


def _markdown_to_tree(
    markdown: str,
    course_id: uuid.UUID,
    source_file: str,
) -> list[CourseContentTree]:
    """Convert Markdown to content tree nodes.

    Enhanced PageIndex pattern with:
    1. Quick heading check (early exit for no-heading documents)
    2. Single-pass code-block-aware tree building (no duplicate scan)
    3. No-heading fallback (paragraph splitting)
    4. Bottom-up token counting + tree thinning (merge small nodes)
    """
    if not markdown or not markdown.strip():
        return []

    lines = markdown.split("\n")

    # Step 1: Quick heading check (early exit, avoids full scan)
    if not _has_headings_code_aware(markdown):
        return _build_tree_from_paragraphs(markdown, course_id, source_file)

    # Step 2: Single-pass tree build from headings (code-block aware)
    nodes: list[CourseContentTree] = []
    stack: list[tuple[int, CourseContentTree]] = []
    order_counter: dict[str, int] = {}
    current_content_lines: list[str] = []

    def flush_content():
        if stack and current_content_lines:
            content = "\n".join(current_content_lines).strip()
            if content:
                stack[-1][1].content = content
        current_content_lines.clear()

    # Root node
    root = CourseContentTree(
        id=uuid.uuid4(),
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

    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Track code blocks
        if CODE_BLOCK_PATTERN.match(stripped):
            in_code_block = not in_code_block
            current_content_lines.append(line)
            continue

        # Only parse headings outside code blocks
        if not in_code_block:
            match = HEADING_PATTERN.match(line)
            if match:
                flush_content()

                level = len(match.group(1))
                title = _sanitize_title(match.group(2))

                while len(stack) > 1 and stack[-1][0] >= level:
                    stack.pop()

                parent = stack[-1][1]
                parent_key = str(parent.id)
                order_counter[parent_key] = order_counter.get(parent_key, 0) + 1

                node = CourseContentTree(
                    id=uuid.uuid4(),
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
                continue

        current_content_lines.append(line)

    flush_content()

    # Step 3: Remove useless root node
    # If root has no content and has children, it's just a structural wrapper.
    # If root has no content AND no children, drop it entirely.
    if len(nodes) > 1 and not nodes[0].content:
        # Root is empty — check if it has exactly one child (unwrap it)
        root_children = [n for n in nodes[1:] if n.parent_id == nodes[0].id]
        if len(root_children) == 1:
            # Promote the single child to root
            root_children[0].parent_id = None
            root_children[0].level = 0
            nodes = nodes[1:]
    elif len(nodes) == 1 and not nodes[0].content:
        # Single empty root — drop it
        return []

    # Step 4: Tree thinning — merge small nodes into parents
    nodes = _thin_tree(nodes)

    return nodes


def _build_tree_from_paragraphs(
    markdown: str,
    course_id: uuid.UUID,
    source_file: str,
) -> list[CourseContentTree]:
    """Build tree from paragraph splits when no headings are found."""
    para_nodes = _split_into_paragraphs(markdown)

    if not para_nodes:
        # Single root node with all content
        root = CourseContentTree(
            id=uuid.uuid4(),
            course_id=course_id,
            parent_id=None,
            title=source_file,
            level=0,
            order_index=0,
            content=markdown.strip(),
            source_file=source_file,
            source_type="pdf",
        )
        return [root]

    nodes: list[CourseContentTree] = []
    root = CourseContentTree(
        id=uuid.uuid4(),
        course_id=course_id,
        parent_id=None,
        title=source_file,
        level=0,
        order_index=0,
        source_file=source_file,
        source_type="pdf",
    )
    nodes.append(root)

    for i, pn in enumerate(para_nodes):
        node = CourseContentTree(
            id=uuid.uuid4(),
            course_id=course_id,
            parent_id=root.id,
            title=pn["title"],
            level=1,
            order_index=i + 1,
            content=pn["text"],
            source_file=source_file,
            source_type="pdf",
        )
        nodes.append(node)

    return nodes


def _thin_tree(nodes: list[CourseContentTree]) -> list[CourseContentTree]:
    """Merge small child nodes into their parent.

    Ported from PageIndex tree_thinning_for_index() (page_index_md.py L135-187).
    Nodes whose subtree has fewer than MIN_NODE_TOKENS get merged upward.
    """
    if len(nodes) <= 2:
        return nodes

    # Build parent→children map
    children_map: dict[str, list[int]] = {}
    for i, node in enumerate(nodes):
        nid = str(node.id)
        pid = str(node.parent_id) if node.parent_id else None
        if pid:
            children_map.setdefault(pid, []).append(i)

    def collect_subtree_indices(root_index: int) -> list[int]:
        """Collect node indices for a subtree in source order."""
        nid = str(nodes[root_index].id)
        result = [root_index]
        for child_index in sorted(children_map.get(nid, [])):
            result.extend(collect_subtree_indices(child_index))
        return result

    # Bottom-up token counting
    token_counts = [0] * len(nodes)
    for i in range(len(nodes) - 1, -1, -1):
        own_text = nodes[i].content or ""
        own_tokens = _count_tokens(own_text) if own_text else 0
        child_tokens = sum(token_counts[ci] for ci in children_map.get(str(nodes[i].id), []))
        token_counts[i] = own_tokens + child_tokens

    # Identify nodes to merge (skip root at index 0)
    indices_to_remove = set()
    for i in range(len(nodes) - 1, 0, -1):
        if i in indices_to_remove:
            continue

        nid = str(nodes[i].id)
        children_indices = children_map.get(nid, [])

        if token_counts[i] < MIN_NODE_TOKENS and children_indices:
            # Merge children content into this node
            merged_parts = []
            if nodes[i].content:
                merged_parts.append(nodes[i].content)

            for ci in sorted(children_indices):
                for subtree_index in collect_subtree_indices(ci):
                    if subtree_index not in indices_to_remove and nodes[subtree_index].content:
                        merged_parts.append(nodes[subtree_index].content)
                    indices_to_remove.add(subtree_index)

            if merged_parts:
                nodes[i].content = "\n\n".join(merged_parts)

    # Remove merged nodes
    result = [n for i, n in enumerate(nodes) if i not in indices_to_remove]
    return result


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
