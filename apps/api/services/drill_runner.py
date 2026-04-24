"""Drill runner — executes submitted code against hidden pytest tests (T6).

Phase 16c practice-first pivot. The runner is the execution half of the
drills loop: a learner's ``submitted_code`` is written into a temp
directory alongside the server-only ``hidden_tests`` and run via
``python -m pytest`` in a subprocess. The caller gets back a
:class:`RunResult` carrying pass/fail, the captured output (truncated
if excessive), and wall-clock duration.

Threat model (MVP)
------------------

This module assumes **trusted learner code** — the sole user of the
drills app is Юрій on his own machine. It is **not** a hostile-user-
grade sandbox. Hardening we DO apply:

* Subprocess isolation via :func:`asyncio.create_subprocess_exec` — no
  shell parsing, explicit argv, so shell-injection vectors in
  ``submitted_code`` are moot (the string never hits ``/bin/sh``).
* Minimal ``env`` (only ``PATH`` + ``PYTHONDONTWRITEBYTECODE``) so API
  keys / DB URLs in the parent process can't leak into the runner.
* ``cwd`` set to a fresh ``tempfile.TemporaryDirectory()`` so writes
  go to a scratch folder that's wiped on exit.
* Hard timeout via :func:`asyncio.wait_for` — infinite loops in
  learner code kill the process group rather than wedge the API.
* Stdout+stderr cap at 8 KB to prevent a malicious/broken print-loop
  from OOM-ing the API worker.

What we do NOT do (yet, punted to later hardening pass):

* Filesystem sandboxing beyond ``cwd`` — submitted code can still
  read ``/etc/passwd``. Fine for a solo-user app; not OK for SaaS.
* Network blocking — submitted code can reach the internet. Same
  disclaimer.
* CPU / memory rlimits — Python has no portable way to set these on
  Windows, and the timeout is the primary defence for now.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


_MAX_OUTPUT_BYTES = 8 * 1024
"""Hard cap on captured runner output (stdout + stderr, decoded).

8 KB is enough for a pytest failure with a tb and a handful of
``print`` lines; anything more is almost always a learner accidentally
writing ``while True: print(x)``. When we truncate we keep the *tail*
because pytest's failure summary (what the learner actually needs to
read) lives at the bottom of the output."""

_TRUNCATION_PREFIX = "...[truncated]...\n"


@dataclass(frozen=True)
class RunResult:
    """Verdict + evidence for a single drill execution.

    ``passed`` is derived strictly from pytest's exit code (``0`` →
    ``True``). A timeout, an OOM kill, or a non-zero exit all count as
    ``passed=False`` — the API/UI layer is free to present any of these
    differently via the output string, but the boolean stays
    unambiguous.
    """

    passed: bool
    output: str
    duration_ms: int


def _truncate(text: str) -> str:
    """Cap ``text`` at :data:`_MAX_OUTPUT_BYTES`, keeping the tail.

    Pytest's failure summary + traceback context live at the bottom of
    the output, so tail-preserving truncation maximises learner signal
    when a print-loop blew up earlier.
    """

    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return text

    budget = _MAX_OUTPUT_BYTES - len(_TRUNCATION_PREFIX.encode("utf-8"))
    tail = encoded[-budget:].decode("utf-8", errors="replace")
    return f"{_TRUNCATION_PREFIX}{tail}"


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Best-effort kill a hung subprocess across platforms.

    ``proc.kill()`` sends SIGKILL on POSIX and ``TerminateProcess`` on
    Windows — both sufficient to reap an infinite loop. We swallow any
    ``ProcessLookupError`` because the process may have already exited
    between the timeout firing and us calling kill.
    """

    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await proc.wait()
    except (ProcessLookupError, asyncio.CancelledError):
        # Raced with natural exit or cooperative cancel — either way
        # the process is gone; don't let the cleanup mask the timeout
        # verdict the caller is about to return.
        pass


async def run_drill(
    submitted_code: str,
    hidden_tests: str,
    *,
    timeout_s: float = 5.0,
) -> RunResult:
    """Run ``submitted_code`` against ``hidden_tests`` in a sandboxed subprocess.

    Args:
        submitted_code: The learner's ``solution.py`` content.
        hidden_tests: Server-only pytest source (``test_drill.py``).
            Never echoed back in the return value beyond what pytest
            itself prints on a failing assertion (pytest shows the
            failing line, which is the intended learner feedback).
        timeout_s: Wall-clock limit. Default 5s is tight enough to kill
            infinite loops quickly while leaving headroom for
            legitimate CPU-bound drills (list comprehensions over a few
            thousand items, small numpy-less algo work).

    Returns:
        :class:`RunResult` with the verdict, captured combined stdout +
        stderr (truncated at 8 KB tail), and duration in milliseconds.
        On timeout the output is a one-line human string; the process
        group is killed before returning.
    """

    start = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="drill_") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "solution.py").write_text(submitted_code, encoding="utf-8")
        (tmp / "test_drill.py").write_text(hidden_tests, encoding="utf-8")

        # Minimal env: PATH (so ``python`` and its entry points resolve
        # on Windows too) + don't-write-bytecode to keep the scratch
        # dir clean. Deliberately no PYTHONPATH, no API keys.
        env = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": os.environ.get("PATH", ""),
        }
        # On Windows, SYSTEMROOT is required for the Python interpreter
        # to start at all; leaving it out produces a bare "Fatal Python
        # error: failed to get random numbers" before user code runs.
        if sys.platform == "win32":
            for key in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
                value = os.environ.get(key)
                if value is not None:
                    env[key] = value

        # ``sys.executable`` keeps us on the same interpreter the API
        # runs under — no surprise 'which python picks the user's
        # conda env' bugs. Argv list, not a shell string, so nothing
        # in learner code can escape out via quoting.
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            "test_drill.py",
            "-q",
            "--tb=short",
            cwd=str(tmp),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            await _terminate(proc)
            duration_ms = int((time.perf_counter() - start) * 1000)
            return RunResult(
                passed=False,
                output=(f"timeout after {timeout_s}s — check for infinite loops"),
                duration_ms=duration_ms,
            )

        returncode = proc.returncode if proc.returncode is not None else -1
        output = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        output = _truncate(output)

        duration_ms = int((time.perf_counter() - start) * 1000)
        return RunResult(
            passed=(returncode == 0),
            output=output,
            duration_ms=duration_ms,
        )


__all__ = [
    "RunResult",
    "run_drill",
]
