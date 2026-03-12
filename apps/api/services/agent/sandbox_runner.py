"""Minimal subprocess sandbox for educational Python execution."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import resource
import signal
import sys


ALLOWED_MODULES = {
    "math", "random", "string", "collections", "itertools",
    "functools", "datetime", "json", "re", "typing",
    "statistics", "decimal", "fractions", "operator",
    "copy", "heapq", "bisect", "array",
}

BLOCKED_BUILTINS = {
    "open", "exec", "eval", "__import__", "compile",
    "globals", "locals", "breakpoint", "exit", "quit",
    "input", "help",
    # Introspection primitives — block sandbox escape via
    # getattr(().__class__, '__bases__')[0].__subclasses__() etc.
    "getattr", "setattr", "delattr", "vars", "dir",
    "type", "memoryview",
}


def _apply_limits() -> None:
    def _safe_set(limit_name: int, soft: int, hard: int) -> None:
        try:
            current_soft, current_hard = resource.getrlimit(limit_name)
            target_hard = min(hard, current_hard if current_hard != resource.RLIM_INFINITY else hard)
            target_soft = min(soft, target_hard)
            resource.setrlimit(limit_name, (target_soft, target_hard))
        except (ValueError, OSError):
            return

    _safe_set(resource.RLIMIT_CPU, 2, 2)
    _safe_set(resource.RLIMIT_FSIZE, 1024 * 1024, 1024 * 1024)
    _safe_set(resource.RLIMIT_NOFILE, 32, 32)
    memory_limit = 256 * 1024 * 1024
    _safe_set(resource.RLIMIT_AS, memory_limit, memory_limit)
    signal.alarm(3)


def _build_globals() -> dict:
    safe_builtins = {
        key: value
        for key, value in builtins.__dict__.items()
        if key not in BLOCKED_BUILTINS
    }
    safe_globals = {"__builtins__": safe_builtins}
    for module_name in ALLOWED_MODULES:
        try:
            safe_globals[module_name] = __import__(module_name)
        except (ImportError, ModuleNotFoundError):
            continue
    return safe_globals


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        code = str(payload.get("code", ""))
        _apply_limits()
        os.environ.clear()

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        safe_globals = _build_globals()

        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exec(code, safe_globals)  # noqa: S102

        sys.stdout.write(json.dumps({
            "success": True,
            "output": stdout_buf.getvalue()[:2000],
            "error": stderr_buf.getvalue()[:500],
        }))
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "success": False,
            "output": "",
            "error": f"{type(exc).__name__}: {exc}",
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
