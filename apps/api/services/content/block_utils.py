"""Block-level utilities for content ownership tracking and manipulation.

Blocks follow the BlockNote JSON schema. Each block carries metadata:
  - owner: "ai" | "user" | "ai+user_edited"
  - locked: bool
"""

import re
import logging

logger = logging.getLogger(__name__)

# Block metadata defaults
DEFAULT_BLOCK_META = {"owner": "ai", "locked": False}


def ensure_block_metadata(block: dict) -> dict:
    """Ensure a block has metadata with owner and locked fields."""
    meta = block.get("metadata") or {}
    meta.setdefault("owner", "ai")
    meta.setdefault("locked", False)
    block["metadata"] = meta
    return block


def separate_blocks_by_owner(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate blocks into replaceable (AI-owned, unlocked) and preserved.

    Returns:
        (replaceable_blocks, preserved_blocks)
        - replaceable: source="ai" AND not locked → safe for AI to overwrite
        - preserved: source="user" OR "ai+user_edited" OR locked → keep as-is
    """
    replaceable = []
    preserved = []
    for block in blocks:
        block = ensure_block_metadata(block)
        meta = block["metadata"]
        if meta.get("locked") or meta.get("owner") in ("user", "ai+user_edited"):
            preserved.append(block)
        else:
            replaceable.append(block)
    return replaceable, preserved


def merge_rewritten_blocks(
    original_blocks: list[dict],
    rewritten_ai_blocks: list[dict],
    preserved_blocks: list[dict],
) -> list[dict]:
    """Merge rewritten AI blocks with preserved user blocks, maintaining order.

    Strategy: Walk original block list. For each block:
    - If it was preserved (user/edited/locked), keep it in place
    - If it was AI-owned, replace with next rewritten block
    - Append any remaining rewritten blocks at the end
    """
    preserved_ids = {id(b) for b in preserved_blocks}
    # Build a map from original block position to preserved block
    preserved_map: dict[int, dict] = {}
    for i, block in enumerate(original_blocks):
        block = ensure_block_metadata(block)
        meta = block["metadata"]
        if meta.get("locked") or meta.get("owner") in ("user", "ai+user_edited"):
            preserved_map[i] = block

    result = []
    rewrite_iter = iter(rewritten_ai_blocks)
    for i, block in enumerate(original_blocks):
        if i in preserved_map:
            result.append(preserved_map[i])
        else:
            replacement = next(rewrite_iter, None)
            if replacement:
                replacement = ensure_block_metadata(replacement)
                replacement["metadata"]["owner"] = "ai"
                result.append(replacement)

    # Append any extra rewritten blocks
    for remaining in rewrite_iter:
        remaining = ensure_block_metadata(remaining)
        remaining["metadata"]["owner"] = "ai"
        result.append(remaining)

    return result


def create_annotation_block(
    text: str,
    annotation_type: str = "tip",
) -> dict:
    """Create a BlockNote-compatible callout/alert block.

    Args:
        text: The annotation content.
        annotation_type: "warning" | "tip" | "correction"
    """
    bg_map = {"warning": "yellow", "tip": "blue", "correction": "red"}
    return {
        "type": "alert",
        "props": {
            "type": annotation_type,
            "backgroundColor": bg_map.get(annotation_type, "default"),
        },
        "content": [{"type": "text", "text": text}],
        "metadata": {"owner": "ai", "locked": False, "annotation_type": annotation_type},
    }


def markdown_to_blocks(markdown_text: str) -> list[dict]:
    """Convert markdown text to a simplified BlockNote block array.

    This is a lightweight server-side converter for ingestion purposes.
    The frontend uses BlockNote's native markdownToBlocks() for full fidelity.
    """
    if not markdown_text:
        return []

    blocks = []
    lines = markdown_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Headings
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            blocks.append({
                "type": "heading",
                "props": {"level": level},
                "content": [{"type": "text", "text": heading_match.group(2).strip()}],
                "metadata": {"owner": "ai", "locked": False},
            })
            i += 1
            continue

        # Bullet list items
        bullet_match = re.match(r"^[\s]*[-*+]\s+(.+)$", line)
        if bullet_match:
            blocks.append({
                "type": "bulletListItem",
                "content": [{"type": "text", "text": bullet_match.group(1).strip()}],
                "metadata": {"owner": "ai", "locked": False},
            })
            i += 1
            continue

        # Numbered list items
        num_match = re.match(r"^[\s]*\d+[.)]\s+(.+)$", line)
        if num_match:
            blocks.append({
                "type": "numberedListItem",
                "content": [{"type": "text", "text": num_match.group(1).strip()}],
                "metadata": {"owner": "ai", "locked": False},
            })
            i += 1
            continue

        # Non-empty paragraphs
        if line.strip():
            blocks.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": line.strip()}],
                "metadata": {"owner": "ai", "locked": False},
            })

        i += 1

    return blocks


def extract_text_from_blocks(blocks: list[dict]) -> str:
    """Extract plain text from BlockNote block array for search indexing."""
    if not blocks:
        return ""

    parts = []
    for block in blocks:
        content = block.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
        elif isinstance(content, str):
            parts.append(content)

        # Recurse into children
        children = block.get("children")
        if isinstance(children, list):
            parts.append(extract_text_from_blocks(children))

    return "\n".join(parts)


def set_all_blocks_locked(blocks: list[dict], locked: bool) -> list[dict]:
    """Set the locked flag on all blocks."""
    for block in blocks:
        block = ensure_block_metadata(block)
        block["metadata"]["locked"] = locked
    return blocks
