"""ReAct loop engine: Think → Tool Call → Observe → Think.

Borrows from:
- HelloAgents ReActAgent: text-based tool_name[input] parsing, Finish[answer]
- HelloAgents FunctionCallAgent: OpenAI native function calling
- OpenAkita reasoning_engine: REASONING → ACTING → OBSERVING cycle
- OpenAkita: loop detection via tool_pattern_window
- NanoBot: interleaved CoT reflection after each tool round

Dual-mode tool invocation:
- Function Calling mode: when LLM provider supports tool_calls (OpenAI, Anthropic)
- Text Parsing mode: when provider doesn't (Ollama, Mock) — regex fallback

Max iterations: configurable (default 3).
"""

import json
import logging
import re
import time
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, TaskPhase
from services.agent.tools.base import MAX_TOOL_RESULT_CHARS, ToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 5

# Use the same truncation limit as base.py for consistency
_TOOL_RESULT_CONTEXT_CHARS = MAX_TOOL_RESULT_CHARS

# Text-mode parsing patterns (HelloAgents ReActAgent pattern)
# Simple pattern for initial detection (actual parsing uses _find_balanced_bracket)
_TOOL_CALL_START = re.compile(r"(\w+)\[")


def _find_balanced_bracket(text: str, open_pos: int) -> int | None:
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


def _build_text_mode_tools_prompt(tools: list, max_iterations: int) -> str:
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


def _parse_text_tool_call(text: str, valid_names: set[str]) -> tuple[str | None, dict | None, str]:
    """Parse a tool call from LLM text output using balanced bracket matching.

    Returns: (tool_name, parsed_input, text_before_call)
    Only returns tool_name if it matches a valid tool name.
    """
    for match in _TOOL_CALL_START.finditer(text):
        tool_name = match.group(1)
        if tool_name not in valid_names:
            continue

        open_pos = match.end() - 1  # Position of the [
        close_pos = _find_balanced_bracket(text, open_pos)
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


def _parse_finish(text: str) -> tuple[str | None, str]:
    """Parse Finish[answer] from text using balanced bracket matching.

    Returns: (answer_text, text_before_finish) or (None, text) if not found.
    """
    idx = text.find("Finish[")
    if idx == -1:
        return None, text
    open_pos = idx + 6  # Position of the [
    close_pos = _find_balanced_bracket(text, open_pos)
    if close_pos is None:
        return None, text
    answer = text[open_pos + 1:close_pos].strip()
    before = text[:idx].strip()
    return answer, before


def _make_call_signature(tool_name: str, params: dict) -> str:
    """Create a signature for loop detection."""
    return f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"


def _record_tool_call(ctx: AgentContext, tool_name: str, tool_input: dict | None, result_output: str, success: bool, iteration: int, duration_ms: float | None = None, error: str | None = None) -> None:
    """Record a tool call in context with consistent format."""
    ctx.tool_calls.append({
        "tool": tool_name,
        "input": tool_input or {},
        "output": result_output[:_TOOL_RESULT_CONTEXT_CHARS],
        "success": success,
        "iteration": iteration,
        "duration_ms": duration_ms,
        "error": error,
    })


# ── Main ReAct Stream ──


async def react_stream(
    client: Any,  # LLMClient
    system_prompt: str,
    user_message: str,
    ctx: AgentContext,
    db: AsyncSession,
    tool_names: list[str],
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AsyncIterator[dict]:
    """Execute ReAct loop, yielding structured events for each step.

    Yields dicts:
    - {"type": "thought", "content": str}     — agent reasoning (not shown to user)
    - {"type": "tool_start", "tool": str, "input": str} — tool invocation
    - {"type": "tool_result", "tool": str, "result": str} — tool result
    - {"type": "answer", "content": str}      — final answer chunk
    - {"type": "answer_done"}                 — answer complete

    Automatically selects function calling or text parsing mode
    based on whether the client supports chat_with_tools().
    """
    registry = get_tool_registry()
    tools = registry.get_tools(tool_names)

    if not tools:
        # No tools available — direct answer (no ReAct)
        full = ""
        async for chunk in client.stream_chat(system_prompt, user_message, images=ctx.images or None):
            full += chunk
            yield {"type": "answer", "content": chunk}
        ctx.response = full
        yield {"type": "answer_done"}
        return

    use_function_calling = hasattr(client, "chat_with_tools")

    if use_function_calling:
        async for event in _react_function_calling(
            client, system_prompt, user_message, ctx, db,
            tools, registry, max_iterations,
        ):
            yield event
    else:
        async for event in _react_text_parsing(
            client, system_prompt, user_message, ctx, db,
            tools, registry, max_iterations,
        ):
            yield event


# ── Function Calling Mode ──


async def _react_function_calling(
    client: Any,
    system_prompt: str,
    user_message: str,
    ctx: AgentContext,
    db: AsyncSession,
    tools: list,
    registry: ToolRegistry,
    max_iterations: int,
) -> AsyncIterator[dict]:
    """ReAct loop using native LLM function calling."""
    tool_schemas = [t.to_openai_schema() for t in tools]

    # Build multimodal user content when images are attached
    user_content: str | list = user_message
    if ctx.images:
        from services.llm.router import _build_openai_user_content
        user_content = _build_openai_user_content(user_message, ctx.images)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    call_history: set[str] = set()  # Loop detection (O(1) lookup)

    used_tools = False
    last_text = ""

    for iteration in range(max_iterations):
        ctx.transition(TaskPhase.REASONING)
        ctx.react_iterations = iteration + 1

        # Call LLM with tools
        try:
            text, tool_calls, usage = await client.chat_with_tools(messages, tool_schemas)
        except Exception as e:
            logger.error("LLM call failed on iteration %d: %s", iteration, e)
            # If we have tool results from prior iterations, build a fallback answer
            if ctx.tool_calls:
                fallback = "I encountered an error generating a complete answer, but here's what I found:\n\n"
                for tc in ctx.tool_calls:
                    if tc["success"]:
                        fallback += f"**{tc['tool']}**: {tc['output'][:800]}\n\n"
                ctx.response = fallback
                yield {"type": "answer", "content": fallback}
                yield {"type": "answer_done"}
                return
            raise  # No tool results — re-raise to caller
        last_text = text or ""

        # Accumulate token usage across all ReAct iterations (not just last call)
        ctx.input_tokens += usage.get("input_tokens", 0)
        ctx.output_tokens += usage.get("output_tokens", 0)

        if not tool_calls:
            # No tool calls — LLM is ready to answer directly
            break

        used_tools = True
        if text:
            yield {"type": "thought", "content": text}

        # Build stable call IDs for all tool_calls in this iteration
        for i, tc in enumerate(tool_calls):
            if "id" not in tc:
                tc["id"] = f"call_{iteration}_{i}"

        # Append assistant message with tool calls
        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if text:
            assistant_msg["content"] = text
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
            }
            for tc in tool_calls
        ]
        messages.append(assistant_msg)

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc["arguments"]
            call_id = tc["id"]

            # Loop detection (OpenAkita pattern)
            sig = _make_call_signature(tool_name, tool_input)
            if sig in call_history:
                logger.info("Skipping duplicate tool call: %s", tool_name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": "(Skipped: duplicate call — same tool and parameters already executed)",
                })
                continue
            call_history.add(sig)

            # Execute tool
            ctx.transition(TaskPhase.ACTING)
            tool_obj = registry.get(tool_name)
            explanation = tool_obj.explain_args(tool_input) if tool_obj else f"Running {tool_name}"
            yield {"type": "tool_start", "tool": tool_name, "input": json.dumps(tool_input, ensure_ascii=False), "explanation": explanation}

            _t0 = time.monotonic()
            result = await registry.execute(
                tool_name, tool_input, ctx, db,
                agent_name=ctx.delegated_agent,
            )
            _duration_ms = (time.monotonic() - _t0) * 1000

            ctx.transition(TaskPhase.OBSERVING)
            result_explanation = tool_obj.explain_result(result) if tool_obj else ""
            yield {"type": "tool_result", "tool": tool_name, "result": result.output[:_TOOL_RESULT_CONTEXT_CHARS], "explanation": result_explanation}

            _record_tool_call(ctx, tool_name, tool_input, result.output, result.success, iteration, duration_ms=_duration_ms, error=result.error)

            # Add tool result to messages (truncated to avoid context overflow)
            tool_content = result.output[:_TOOL_RESULT_CONTEXT_CHARS] if result.success else f"Error: {result.error or result.output or 'unknown error'}"
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_content,
            })
    else:
        # Exhausted iterations — force final answer
        messages.append({
            "role": "user",
            "content": "You have used all available tool calls. Now provide your final answer based on the information gathered.",
        })

    if not used_tools and last_text:
        # LLM provided an answer without using any tools — use it directly
        # (avoids wasting an extra LLM call to regenerate the same answer)
        ctx.response = last_text
        yield {"type": "answer", "content": last_text}
        yield {"type": "answer_done"}
        return

    # Generate final answer after tool use (stream it)
    full_answer = ""
    async for chunk in client.stream_chat(
        system_prompt,
        _messages_to_user_content(messages),
        images=ctx.images or None,
    ):
        full_answer += chunk
        yield {"type": "answer", "content": chunk}

    ctx.response = full_answer
    yield {"type": "answer_done"}


# ── Text Parsing Mode ──


async def _react_text_parsing(
    client: Any,
    system_prompt: str,
    user_message: str,
    ctx: AgentContext,
    db: AsyncSession,
    tools: list,
    registry: ToolRegistry,
    max_iterations: int,
) -> AsyncIterator[dict]:
    """ReAct loop using text-based tool_name[input] parsing (HelloAgents pattern)."""
    enhanced_prompt = system_prompt + _build_text_mode_tools_prompt(tools, max_iterations)
    call_history: set[str] = set()
    valid_tool_names = {t.name for t in tools}

    # Build conversation as a single growing text
    conversation_parts = [user_message]

    for iteration in range(max_iterations):
        ctx.transition(TaskPhase.REASONING)
        ctx.react_iterations = iteration + 1

        # Call LLM (pass images on first iteration so LLM can see attachments)
        full_text = ""
        combined_user = "\n\n".join(conversation_parts)
        iter_images = (ctx.images or None) if iteration == 0 else None
        async for chunk in client.stream_chat(enhanced_prompt, combined_user, images=iter_images):
            full_text += chunk

        # Check for Finish[answer]
        answer, before = _parse_finish(full_text)
        if answer is not None:
            if before:
                yield {"type": "thought", "content": before}
            ctx.response = answer
            yield {"type": "answer", "content": answer}
            yield {"type": "answer_done"}
            return

        # Check for tool call (only matches valid tool names)
        tool_name, tool_input, before_text = _parse_text_tool_call(full_text, valid_tool_names)
        if not tool_name:
            # No valid tool call found — treat as final answer
            ctx.response = full_text
            yield {"type": "answer", "content": full_text}
            yield {"type": "answer_done"}
            return

        if before_text:
            yield {"type": "thought", "content": before_text}

        # Loop detection
        safe_input = tool_input or {}
        sig = _make_call_signature(tool_name, safe_input)
        if sig in call_history:
            logger.info("Skipping duplicate text-mode tool call: %s", tool_name)
            conversation_parts.append(f"Observation: (Skipped duplicate call to {tool_name})")
            continue
        call_history.add(sig)

        # Execute tool
        ctx.transition(TaskPhase.ACTING)
        tool_obj = registry.get(tool_name)
        explanation = tool_obj.explain_args(safe_input) if tool_obj else f"Running {tool_name}"
        yield {"type": "tool_start", "tool": tool_name, "input": json.dumps(safe_input, ensure_ascii=False), "explanation": explanation}

        _t0 = time.monotonic()
        result = await registry.execute(
            tool_name, safe_input, ctx, db,
            agent_name=ctx.delegated_agent,
        )
        _duration_ms = (time.monotonic() - _t0) * 1000

        ctx.transition(TaskPhase.OBSERVING)
        result_explanation = tool_obj.explain_result(result) if tool_obj else ""
        yield {"type": "tool_result", "tool": tool_name, "result": result.output[:_TOOL_RESULT_CONTEXT_CHARS], "explanation": result_explanation}

        _record_tool_call(ctx, tool_name, safe_input, result.output, result.success, iteration, duration_ms=_duration_ms, error=result.error)

        # Append observation for next iteration
        obs = result.output if result.success else f"Error: {result.error or result.output or 'unknown error'}"
        conversation_parts.append(
            f"Assistant: {full_text}\n\nObservation: {obs}\n\n"
            "Continue reasoning. Call another tool or write Finish[your answer]."
        )

    # Exhausted iterations — force final answer
    conversation_parts.append(
        "You have used all available tool calls. "
        "Now write Finish[your complete answer] based on what you have gathered."
    )
    full_text = ""
    combined_user = "\n\n".join(conversation_parts)
    async for chunk in client.stream_chat(enhanced_prompt, combined_user, images=ctx.images or None):
        full_text += chunk

    # Try to extract Finish[...] from forced answer
    extracted_answer, _ = _parse_finish(full_text)
    answer = extracted_answer if extracted_answer is not None else full_text
    ctx.response = answer
    yield {"type": "answer", "content": answer}
    yield {"type": "answer_done"}


# ── Helpers ──


def _messages_to_user_content(messages: list[dict]) -> str:
    """Flatten a messages list into a single user-content string for stream_chat().

    Used when falling back from chat_with_tools to stream_chat for the final answer.
    Handles both OpenAI and Anthropic message formats.
    """
    parts = []
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
