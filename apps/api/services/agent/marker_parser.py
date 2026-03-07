"""Shared streaming marker parser for [TOOL_START:], [TOOL_DONE:], [ACTION:] markers.

Used by the orchestrator to parse tool-use and action markers out of streamed
LLM responses so they can be forwarded as structured SSE events.
"""

import logging
import re

logger = logging.getLogger(__name__)

_INCOMPLETE_MARKER_RE = re.compile(r"\[(TOOL_START|TOOL_DONE|ACTION):[^\]]*$")

# ── Marker types for the shared parser ──
_MARKER_TAGS = ("TOOL_START", "TOOL_DONE", "ACTION")
_MARKER_PREFIXES = tuple(f"[{tag}:" for tag in _MARKER_TAGS)


def _parse_action_marker(marker: str) -> dict:
    parts = marker.split(":")
    action_data = {"action": parts[0]}
    if len(parts) >= 2:
        action_data["value"] = parts[1]
    if len(parts) >= 3:
        # Preserve additional colons in free-form text payloads.
        action_data["extra"] = ":".join(parts[2:])
    return action_data


class MarkerParser:
    """Shared parser for [TOOL_START:], [TOOL_DONE:], [ACTION:] markers in streamed text.

    Call ``feed(chunk)`` for each incoming chunk. It returns a list of events:
    - ("text", str)         -- plain text content
    - ("tool_start", dict)  -- {"tool": name, "explanation": str}
    - ("tool_done", dict)   -- {"tool": name, "explanation": str}
    - ("action", dict)      -- parsed action marker
    """

    __slots__ = ("_buffer",)

    def __init__(self):
        self._buffer = ""

    def _has_pending(self) -> bool:
        return any(p in self._buffer for p in _MARKER_PREFIXES)

    def _parse_tool_marker(self, raw: str) -> tuple[str, str]:
        if "|" in raw:
            name, explanation = raw.split("|", 1)
        else:
            name, explanation = raw, ""
        return name, explanation

    def feed(self, chunk: str) -> list[tuple[str, str | dict]]:
        """Feed a chunk and return parsed events."""
        self._buffer += chunk
        events: list[tuple[str, str | dict]] = []

        changed = True
        while changed:
            changed = False

            if "[TOOL_START:" in self._buffer:
                start = self._buffer.index("[TOOL_START:")
                end = self._buffer.find("]", start)
                if end != -1:
                    before = self._buffer[:start]
                    if before:
                        events.append(("text", before))
                    name, explanation = self._parse_tool_marker(self._buffer[start + 12:end])
                    events.append(("tool_start", {"tool": name, "explanation": explanation}))
                    self._buffer = self._buffer[end + 1:]
                    changed = True
                    continue

            if "[TOOL_DONE:" in self._buffer:
                start = self._buffer.index("[TOOL_DONE:")
                end = self._buffer.find("]", start)
                if end != -1:
                    before = self._buffer[:start]
                    if before:
                        events.append(("text", before))
                    name, explanation = self._parse_tool_marker(self._buffer[start + 11:end])
                    events.append(("tool_done", {"tool": name, "explanation": explanation}))
                    self._buffer = self._buffer[end + 1:]
                    changed = True
                    continue

            if "[ACTION:" in self._buffer:
                start = self._buffer.index("[ACTION:")
                end = self._buffer.find("]", start)
                if end != -1:
                    before = self._buffer[:start]
                    if before:
                        events.append(("text", before))
                    marker = self._buffer[start + 8:end]
                    events.append(("action", _parse_action_marker(marker)))
                    self._buffer = self._buffer[end + 1:]
                    changed = True
                    continue

        # Flush safe buffer content
        if self._buffer and not self._has_pending():
            events.append(("text", self._buffer))
            self._buffer = ""
        elif self._has_pending() and len(self._buffer) > 500:
            logger.warning("Flushing oversized marker buffer (%d chars)", len(self._buffer))
            events.append(("text", self._buffer))
            self._buffer = ""

        return events

    def flush(self) -> str | None:
        """Flush remaining buffer, stripping incomplete markers."""
        if not self._buffer:
            return None
        cleaned = _INCOMPLETE_MARKER_RE.sub("", self._buffer)
        self._buffer = ""
        return cleaned or None
