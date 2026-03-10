"""Helper functions for the ReAct loop engine.

Extracted from react_loop.py: text parsing, bracket matching,
prompt building, tool call recording, and message flattening.
"""

import json
import re
from typing import Any

from services.agent.state import AgentContext
from services.agent.tools.base import MAX_TOOL_RESULT_CHARS

# Use the same truncation limit as base.py for consistency
TOOL_RESULT_CONTEXT_CHARS = MAX_TOOL_RESULT_CHARS

# Text-mode parsing patterns (HelloAgents ReActAgent pattern)
# Simple pattern for initial detection (actual parsing uses _find_balanced_bracket)
TOOL_CALL_START = re.compile(r"(\w+)\[")


def find_balanced_bracket(text: str, open_pos: int) -> int | None:
    """Find the closing ] that balances the [ at open_pos, handling nested brackets.

    Returns the index of the closing bracket, or None if not found.
    """
    depth = 0
    in_string = False
    escape_next = False
    for i in range(open_pos, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\":
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
    return None


def build_text_mode_tools_prompt(tools: list, max_iterations: int) -> str:
    """Build the tool description section for text-based parsing mode."""
    tool_descs = "\n".join(t.to_text_description() for t in tools)
    return f"""

## Available Tools
You can call tools to gather information before answering.
To call a tool, write on its own line: tool_name[{{"param": "value"}}]
When you have enough information, write: Finish[your final answer]
You may call at most {max_iterations} tools.

{tool_descs}

## Response Format
1. Think about what information you need.
2. Call a tool if needed: tool_name[{{"param": "value"}}]
3. After receiving the observation, think again.
4. When ready, write: Finish[your complete answer to the student]
"""


def parse_text_tool_call(text: str, valid_names: set[str]) -> tuple[str | None, dict | None, str]:
    """Parse a tool call from LLM text output using balanced bracket matching.

    Returns: (tool_name, parsed_input, text_before_call)
    Only returns tool_name if it matches a valid tool name.
    """
    for match in TOOL_CALL_START.finditer(text):
        tool_name = match.group(1)
        if tool_name not in valid_names:
            continue

        open_pos = match.end() - 1  # Position of the [
        close_pos = find_balanced_bracket(text, open_pos)
        if close_pos is None:
            continue  # Unbalanced brackets, skip

        raw_input = text[open_pos + 1:close_pos].strip()
        before = text[:match.start()].strip()

        # Parse input as JSON; fall back using tool's first param name
        try:
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                parsed = {"query": str(parsed)}
        except (json.JSONDecodeError, TypeError):
            parsed = {"query": raw_input}

        return tool_name, parsed, before

    return None, None, text


def parse_finish(text: str) -> tuple[str | None, str]:
    """Parse Finish[answer] from text using balanced bracket matching.

    Returns: (answer_text, text_before_finish) or (None, text) if not found.
    """
    idx = text.find("Finish[")
    if idx == -1:
        return None, text
    open_pos = idx + 6  # Position of the [
    close_pos = find_balanced_bracket(text, open_pos)
    if close_pos is None:
        return None, text
    answer = text[open_pos + 1:close_pos].strip()
    before = text[:idx].strip()
    return answer, before


def make_call_signature(tool_name: str, params: dict) -> str:
    """Create a signature for loop detection."""
    return f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"


def record_tool_call(
    ctx: AgentContext,
    tool_name: str,
    tool_input: dict | None,
    result_output: str,
    success: bool,
    iteration: int,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Record a tool call in context with consistent format."""
    ctx.tool_calls.append({
        "tool": tool_name,
        "input": tool_input or {},
        "output": result_output[:TOOL_RESULT_CONTEXT_CHARS],
        "success": success,
        "iteration": iteration,
        "duration_ms": duration_ms,
        "error": error,
    })


def messages_to_user_content(messages: list[dict]) -> str:
    """Flatten a messages list into a single user-content string for stream_chat().

    Used when falling back from chat_with_tools to stream_chat for the final answer.
    Handles both OpenAI and Anthropic message formats.
    """
    parts: list[str] = []
    for msg in messages[1:]:  # Skip system message
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                # Anthropic format: content blocks
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            parts.append(f"[Tool result]: {block.get('content', '')}")

        elif role == "assistant":
            if isinstance(content, str) and content:
                parts.append(f"[Assistant thought]: {content}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(f"[Assistant thought]: {block.get('text', '')}")
                        elif block.get("type") == "tool_use":
                            parts.append(f"[Tool call: {block.get('name', '?')}]")
            # Also capture tool_calls from OpenAI format (assistant with no text content)
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", tc)
                    parts.append(f"[Tool call: {func.get('name', '?')}]")

        elif role == "tool":
            if isinstance(content, str):
                parts.append(f"[Tool result]: {content}")

    return "\n\n".join(parts)


# Backward-compatible aliases (underscore-prefixed names used in react_loop.py)
_find_balanced_bracket = find_balanced_bracket
_build_text_mode_tools_prompt = build_text_mode_tools_prompt
_parse_text_tool_call = parse_text_tool_call
_parse_finish = parse_finish
_make_call_signature = make_call_signature
_record_tool_call = record_tool_call
_messages_to_user_content = messages_to_user_content
_TOOL_RESULT_CONTEXT_CHARS = TOOL_RESULT_CONTEXT_CHARS
_TOOL_CALL_START = TOOL_CALL_START
