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
from contextvars import ContextVar
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)

_sandbox_backend_override: ContextVar[str | None] = ContextVar("sandbox_backend_override", default=None)


def process_sandbox_allowed() -> bool:
    return bool(
        settings.allow_insecure_process_sandbox
        or os.environ.get("PYTEST_CURRENT_TEST")
    )


def get_effective_sandbox_backend() -> str:
    backend = _sandbox_backend_override.get() or settings.code_sandbox_backend
    if backend == "process":
        if process_sandbox_allowed():
            return backend
        logger.warning("Process sandbox requested outside test/dev override; forcing container backend.")
        return "container"
    if backend == "auto" and not process_sandbox_allowed():
        return "container"
    return backend


def push_sandbox_backend_override(backend: str):
    return _sandbox_backend_override.set(backend)


def pop_sandbox_backend_override(token) -> None:
    _sandbox_backend_override.reset(token)


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
        r"\bfrom\s+(os|sys|subprocess|shutil|socket|http|urllib|requests|pathlib)\b",
        r"\b__import__\s*\(", r"\beval\s*\(", r"\bexec\s*\(",
        r"\bopen\s*\(", r"\bcompile\s*\(", r"\bglobals\s*\(",
        r"\bbreakpoint\s*\(",
        r"\bgetattr\s*\(", r"\bsetattr\s*\(",
        r"\b__subclasses__\s*\(", r"\b__bases__\b", r"\b__mro__\b",
        r"\bimport\s+importlib\b", r"\bfrom\s+importlib\b",
        r"\bimport\s+ctypes\b", r"\bfrom\s+ctypes\b",
        r"\bimport\s+pickle\b", r"\bfrom\s+pickle\b",
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
        # Enforce module whitelist: reject any import not in ALLOWED_MODULES
        for m in re.finditer(r"^\s*(?:import|from)\s+(\w+)", code, re.MULTILINE):
            module_name = m.group(1)
            if module_name not in self.ALLOWED_MODULES:
                return False, f"Module '{module_name}' is not in the allowed list for safe execution"
        # Check code length
        if len(code) > 5000:
            return False, "Code too long (max 5000 characters)"
        # Check for infinite loop indicators (while True, while 1, while not False, etc.)
        if re.search(r"while\s+(True|1|not\s+False)\s*:", code):
            # Only allow if "break" appears as an actual statement (not in strings/comments)
            code_lines = [l.split("#")[0] for l in code.split("\n")]  # strip comments
            has_break = any(re.search(r"\bbreak\b", l) for l in code_lines)
            if not has_break:
                return False, "Potential infinite loop detected (while True without break)"
        return True, "OK"

    def _execute_in_process_sandbox(self, code: str) -> dict:
        """Execute code in an isolated subprocess with resource limits."""
        runner_path = Path(__file__).with_name("sandbox_runner.py")
        payload = json.dumps({"code": code})

        with tempfile.TemporaryDirectory(prefix="opentutor-code-") as tempdir:
            env = {"PYTHONIOENCODING": "utf-8"}
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", str(runner_path)],
                    input=payload,
                    text=True,
                    capture_output=True,
                    timeout=settings.code_sandbox_timeout_seconds,
                    cwd=tempdir,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "output": "",
                    "error": f"Execution timed out after {settings.code_sandbox_timeout_seconds} seconds",
                    "backend": "process",
                }
            except Exception as e:
                return {
                    "success": False,
                    "output": "",
                    "error": f"{type(e).__name__}: {e}",
                    "backend": "process",
                }

        raw = (completed.stdout or "").strip()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {
                "success": False,
                "output": (completed.stdout or "")[:2000],
                "error": (completed.stderr or "Sandbox returned invalid JSON")[:500],
            }

        if completed.returncode != 0 and parsed.get("success", False):
            parsed["success"] = False
            parsed["error"] = (completed.stderr or "Sandbox process failed")[:500]

        return {
            "success": bool(parsed.get("success")),
            "output": str(parsed.get("output", ""))[:2000],
            "error": str(parsed.get("error", ""))[:500],
            "backend": "process",
        }

    def _execute_safe(self, code: str) -> dict:
        """Execute code in the configured sandbox backend."""
        from services.agent.container_sandbox import (
            ContainerSandboxUnavailable,
            execute_in_container,
        )

        runner_path = Path(__file__).with_name("sandbox_runner.py")
        backend = get_effective_sandbox_backend()

        if backend in {"auto", "container"}:
            try:
                return execute_in_container(code, runner_path=runner_path)
            except ContainerSandboxUnavailable as exc:
                if backend == "container" or not process_sandbox_allowed():
                    return {"success": False, "output": "", "error": str(exc), "backend": "container"}
                logger.info("Container sandbox unavailable, falling back to process sandbox: %s", exc)

        return self._execute_in_process_sandbox(code)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Extract code, validate, execute, then generate explanation."""
        code = self._extract_code(ctx.user_message)

        if code:
            safe, reason = self._validate_code(code)
            if safe:
                result = await asyncio.to_thread(self._execute_safe, code)
                ctx.metadata["code_result"] = result
                ctx.metadata["code_snippet"] = code
                ctx.metadata["sandbox_backend"] = result.get("backend")
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

        client = self.get_llm_client(ctx)
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
                ctx.metadata["sandbox_backend"] = result.get("backend")
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

        client = self.get_llm_client(ctx)
        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message):
            full_response += chunk
            yield chunk
        ctx.response = full_response
