"""Per-channel response formatting — adapts AI output for each messaging platform.

Each platform has different capabilities and constraints:
- WhatsApp: limited markdown (*bold* only), 4096 char limit, no LaTeX
- iMessage: plain text only, 10000 char limit, no markdown/LaTeX
- Web: full markdown, no limit (passthrough)

Strips internal markers ([ACTION:...], [TOOL_START/DONE:...]) before formatting.
"""

import re

# Maximum message length per channel (None = no limit)
CHANNEL_MAX_LENGTH: dict[str, int | None] = {
    "whatsapp": 4096,
    "imessage": 10000,
    "web": None,
}

# Internal marker patterns to strip before user-facing output
_MARKER_PATTERN = re.compile(
    r"\[(ACTION|TOOL_START|TOOL_DONE):[^\]]*\]"
)


def format_for_channel(text: str, channel_type: str) -> str:
    """Format AI response text for a specific messaging channel.

    Pipeline:
    1. Strip internal [ACTION:...] and [TOOL_START/DONE:...] markers
    2. Apply per-channel formatting transformations
    3. Truncate to channel's max length with ellipsis indicator
    """
    # 1. Strip internal markers
    cleaned = _MARKER_PATTERN.sub("", text)

    # 2. Per-channel formatting
    formatters = {
        "whatsapp": _format_whatsapp,
        "imessage": _format_imessage,
    }
    formatter = formatters.get(channel_type)
    if formatter:
        cleaned = formatter(cleaned)

    # 3. Truncate to max length
    max_len = CHANNEL_MAX_LENGTH.get(channel_type)
    if max_len and len(cleaned) > max_len:
        truncation_note = "\n\n... (message truncated)"
        cleaned = cleaned[: max_len - len(truncation_note)] + truncation_note

    # Final cleanup: collapse excessive blank lines
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)

    return cleaned.strip()


def _format_whatsapp(text: str) -> str:
    """Format text for WhatsApp's limited markdown support.

    Transformations:
    - ### headings -> *bold* text
    - **bold** -> *bold* (WhatsApp single asterisk)
    - [link text](url) -> "text: url" (no hyperlinks in WhatsApp)
    - Strip $LaTeX$ blocks
    - Clean excessive newlines
    """
    result = text

    # Headings: ### Title -> *Title*
    result = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", result, flags=re.MULTILINE)

    # Bold: **text** -> *text*
    result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)

    # Inline code: `code` -> code (WhatsApp uses ``` for code blocks but not inline)
    result = re.sub(r"`([^`\n]+)`", r"\1", result)

    # Code blocks: ```lang\ncode\n``` -> just the code with ``` preserved
    # WhatsApp supports ``` code blocks natively, so leave them

    # Links: [text](url) -> text: url
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", result)

    # Images: ![alt](url) -> (Image: alt)
    result = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"(Image: \1)", result)

    # Strip inline LaTeX: $formula$ -> (formula)
    result = re.sub(r"\$([^$]+)\$", r"(\1)", result)

    # Strip block LaTeX: $$...$$ -> (formula)
    result = re.sub(r"\$\$([^$]+)\$\$", r"(\1)", result, flags=re.DOTALL)

    # Horizontal rules: --- or *** -> simple separator
    result = re.sub(r"^[-*]{3,}\s*$", "---", result, flags=re.MULTILINE)

    # Bullet lists: normalize various markdown bullets
    result = re.sub(r"^(\s*)[*+-]\s+", r"\1- ", result, flags=re.MULTILINE)

    # Clean excessive newlines
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result


def _format_imessage(text: str) -> str:
    """Format text for iMessage — strip all markdown, keep plain text.

    iMessage has no markdown rendering, so all formatting is removed
    to avoid visual clutter from raw markdown syntax.
    """
    result = text

    # Strip headings: ### Title -> Title
    result = re.sub(r"^#{1,6}\s+", "", result, flags=re.MULTILINE)

    # Strip bold/italic: **text** -> text, *text* -> text, __text__ -> text, _text_ -> text
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)
    result = re.sub(r"\*(.+?)\*", r"\1", result)
    result = re.sub(r"__(.+?)__", r"\1", result)
    result = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", result)

    # Strip inline code backticks
    result = re.sub(r"`([^`\n]+)`", r"\1", result)

    # Strip code block markers but keep content
    result = re.sub(r"```\w*\n?", "", result)

    # Links: [text](url) -> text (url)
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", result)

    # Images: ![alt](url) -> (Image: alt)
    result = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"(Image: \1)", result)

    # Strip inline LaTeX
    result = re.sub(r"\$([^$]+)\$", r"\1", result)

    # Strip block LaTeX
    result = re.sub(r"\$\$([^$]+)\$\$", r"\1", result, flags=re.DOTALL)

    # Strip horizontal rules
    result = re.sub(r"^[-*]{3,}\s*$", "", result, flags=re.MULTILINE)

    # Normalize bullet lists to simple dashes
    result = re.sub(r"^(\s*)[*+]\s+", r"\1- ", result, flags=re.MULTILINE)

    # Strip blockquotes
    result = re.sub(r"^>\s?", "", result, flags=re.MULTILINE)

    # Clean excessive newlines
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result
