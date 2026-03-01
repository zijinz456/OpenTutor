"""Container-backed sandbox for educational code execution."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


class ContainerSandboxUnavailable(RuntimeError):
    """Raised when the configured container runtime is unavailable."""


def _build_container_command(runner_path: Path) -> list[str]:
    runtime = settings.code_sandbox_runtime
    return [
        runtime,
        "run",
        "--rm",
        "--read-only",
        "--network",
        "none",
        "--user",
        "65534:65534",
        "--cpus",
        "1",
        "--memory",
        "256m",
        "--pids-limit",
        "64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-i",
        "-v",
        f"{runner_path}:/sandbox_runner.py:ro",
        "-w",
        "/tmp",
        settings.code_sandbox_image,
        "python",
        "-I",
        "/sandbox_runner.py",
    ]


def container_runtime_available() -> bool:
    return shutil.which(settings.code_sandbox_runtime) is not None


def execute_in_container(code: str, *, runner_path: Path) -> dict:
    if not container_runtime_available():
        raise ContainerSandboxUnavailable(
            f"{settings.code_sandbox_runtime} runtime not available"
        )

    payload = json.dumps({"code": code})
    command = _build_container_command(runner_path)
    try:
        completed = subprocess.run(
            command,
            input=payload,
            text=True,
            capture_output=True,
            timeout=settings.code_sandbox_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": f"Container sandbox timed out after {settings.code_sandbox_timeout_seconds} seconds",
            "backend": "container",
        }

    raw = (completed.stdout or "").strip()
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("Container sandbox returned invalid JSON: %s", raw[:200])
        parsed = {
            "success": False,
            "output": (completed.stdout or "")[:2000],
            "error": (completed.stderr or "Container sandbox returned invalid JSON")[:500],
        }

    if completed.returncode != 0 and parsed.get("success", False):
        parsed["success"] = False
        parsed["error"] = (completed.stderr or "Container sandbox failed")[:500]

    return {
        "success": bool(parsed.get("success")),
        "output": str(parsed.get("output", ""))[:2000],
        "error": str(parsed.get("error", ""))[:500],
        "backend": "container",
    }
