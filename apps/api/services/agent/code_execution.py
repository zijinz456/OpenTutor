"""CodeExecutionAgent — safe Python code execution for STEM tutoring.

Borrows from:
- HelloAgents code_runner.py: restricted globals + I/O stream capture
- OpenClaw Sandbox: workspace access control, blocked module patterns
- Spec Section 4: STEM course support with interactive code execution

Provides safe execution of student code snippets with:
- Module allowlist (math, collections, itertools, etc.)
- Dangerous pattern blocklist (os, sys, subprocess, open, eval, exec)
- Execution timeout (5s default)
- Captured stdout/stderr for explanation
"""

import asyncio
import concurrent.futures
import contextlib
import io
import json
import logging
import re
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class CodeExecutionAgent(BaseAgent):
    """Handles code execution requests with safety validation."""

    name = "code_execution"
    profile = (
        "You are a programming tutor that can execute Python code safely.\n"
        "When the student provides code, analyze it and explain the output.\n"
        "If there are errors, explain them clearly and suggest fixes.\n"
        "Always validate code safety before execution.\n"
        "Use the code execution result provided below to guide your explanation.\n"
        "If no code was found, help the student write correct code."
    )
    model_preference = "large"

    # Safety: allowed standard library modules
    ALLOWED_MODULES = {
        "math", "random", "string", "collections", "itertools",
        "functools", "datetime", "json", "re", "typing",
        "statistics", "decimal", "fractions", "operator",
        "copy", "heapq", "bisect", "array",
    }

    # Safety: blocked dangerous patterns
    BLOCKED_PATTERNS = [
        r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
        r"\bimport\s+shutil\b", r"\bimport\s+socket\b", r"\bimport\s+http\b",
        r"\bimport\s+urllib\b", r"\bimport\s+requests\b", r"\bimport\s+pathlib\b",
        r"\b__import__\s*\(", r"\beval\s*\(", r"\bexec\s*\(",
        r"\bopen\s*\(", r"\bcompile\s*\(", r"\bglobals\s*\(",
        r"\bbreakpoint\s*\(",
    ]

    MAX_EXECUTION_TIME = 5  # seconds

    def _extract_code(self, message: str) -> str | None:
        """Extract code block from user message.

        Supports ```python ... ``` and ```...``` fences.
        """
        # Try fenced code block first
        fence_pattern = r"```(?:python|py)?\s*\n(.*?)```"
        match = re.search(fence_pattern, message, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Try indented code block (4+ spaces or tab)
        lines = message.split("\n")
        code_lines = [l for l in lines if l.startswith("    ") or l.startswith("\t")]
        if len(code_lines) >= 2:
            return "\n".join(l.lstrip() for l in code_lines)

        return None

    def _validate_code(self, code: str) -> tuple[bool, str]:
        """Check code safety before execution (HelloAgents CodeRunner pattern)."""
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, code):
                return False, f"Blocked: pattern '{pattern}' is not allowed for safety"
        # Check code length
        if len(code) > 5000:
            return False, "Code too long (max 5000 characters)"
        # Check for infinite loop indicators
        if re.search(r"while\s+True\s*:", code) and "break" not in code:
            return False, "Potential infinite loop detected (while True without break)"
        return True, "OK"

    def _execute_safe(self, code: str) -> dict:
        """Execute code in restricted sandbox (HelloAgents CodeRunner pattern).

        Uses restricted builtins, captured I/O streams, and enforced timeout.
        """
        import builtins

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        # Build restricted builtins
        blocked_builtins = {"open", "exec", "eval", "__import__", "compile",
                            "globals", "locals", "breakpoint", "exit", "quit"}
        safe_builtins = {k: v for k, v in builtins.__dict__.items()
                         if k not in blocked_builtins}

        safe_globals: dict = {"__builtins__": safe_builtins}

        # Pre-import allowed modules
        for mod_name in self.ALLOWED_MODULES:
            try:
                safe_globals[mod_name] = __import__(mod_name)
            except ImportError:
                pass

        def _run():
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(code, safe_globals)  # noqa: S102 — sandboxed exec

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run)
                future.result(timeout=self.MAX_EXECUTION_TIME)
            return {
                "success": True,
                "output": stdout_buf.getvalue()[:2000],
                "error": stderr_buf.getvalue()[:500],
            }
        except concurrent.futures.TimeoutError:
            return {
                "success": False,
                "output": stdout_buf.getvalue()[:2000],
                "error": f"Execution timed out after {self.MAX_EXECUTION_TIME} seconds",
            }
        except Exception as e:
            return {
                "success": False,
                "output": stdout_buf.getvalue()[:2000],
                "error": f"{type(e).__name__}: {e}",
            }

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Extract code, validate, execute, then generate explanation."""
        code = self._extract_code(ctx.user_message)

        if code:
            safe, reason = self._validate_code(code)
            if safe:
                result = await asyncio.to_thread(self._execute_safe, code)
                ctx.metadata["code_result"] = result
                ctx.metadata["code_snippet"] = code
            else:
                ctx.metadata["code_result"] = {"success": False, "output": "", "error": reason}
                ctx.metadata["code_snippet"] = code

        # Build prompt with code execution context
        system_prompt = self.build_system_prompt(ctx)
        if ctx.metadata.get("code_result"):
            result = ctx.metadata["code_result"]
            system_prompt += (
                f"\n\n## Code Execution Result:\n"
                f"```\nCode:\n{ctx.metadata.get('code_snippet', '')}\n\n"
                f"Success: {result['success']}\n"
                f"Output: {result['output']}\n"
                f"Error: {result['error']}\n```"
            )

        client = self.get_llm_client()
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream code execution response."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        # Extract and execute code first
        code = self._extract_code(ctx.user_message)
        if code:
            safe, reason = self._validate_code(code)
            if safe:
                result = await asyncio.to_thread(self._execute_safe, code)
                ctx.metadata["code_result"] = result
                ctx.metadata["code_snippet"] = code
            else:
                ctx.metadata["code_result"] = {"success": False, "output": "", "error": reason}
                ctx.metadata["code_snippet"] = code

        system_prompt = self.build_system_prompt(ctx)
        if ctx.metadata.get("code_result"):
            result = ctx.metadata["code_result"]
            system_prompt += (
                f"\n\n## Code Execution Result:\n"
                f"```\nCode:\n{ctx.metadata.get('code_snippet', '')}\n\n"
                f"Success: {result['success']}\n"
                f"Output: {result['output']}\n"
                f"Error: {result['error']}\n```"
            )

        client = self.get_llm_client()
        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message):
            full_response += chunk
            yield chunk
        ctx.response = full_response
