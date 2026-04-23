"""Eval-suite runner.

``run_eval_suite`` loads one or more YAML fixtures of canned questions,
dispatches them concurrently through the existing LLM router
(``services.llm.router.get_llm_client``), grades each answer, and
returns an :class:`EvalReport`.

Design invariants:

* Never raises on individual question failure — a provider error is
  recorded as ``passed=False`` with an ``error`` field and the suite
  keeps going. Only unrecoverable conditions raise
  (``all fixtures missing`` / ``no LLM providers configured``).
* Concurrency is bounded by a ``Semaphore`` to avoid overwhelming
  single-key providers / rate limits.
* Report model + provider names are sourced from the actual client
  the router returned, so variant routing (large/small/fast) is
  reflected honestly in the report header.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

from schemas.eval import EvalQuestion, EvalReport, EvalResult
from services.eval.grader import grade_answer, grade_answer_judge

logger = logging.getLogger(__name__)


# ── Fixture loading ──────────────────────────────────────────


def load_questions(fixture_paths: Iterable[Path]) -> list[EvalQuestion]:
    """Load and validate all questions from the given YAML fixtures.

    Missing files are logged and skipped. Malformed entries raise
    ``pydantic.ValidationError`` — we want loud failures on broken
    fixtures because they'd otherwise silently skew the score.
    """
    questions: list[EvalQuestion] = []
    for path in fixture_paths:
        path = Path(path)
        if not path.exists():
            logger.warning("Fixture not found, skipping: %s", path)
            continue
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        raw_qs = data.get("questions", [])
        for raw in raw_qs:
            questions.append(EvalQuestion.model_validate(raw))
    return questions


# ── Runner ───────────────────────────────────────────────────


async def _run_one_question(
    q: EvalQuestion,
    llm_client,
    semaphore: asyncio.Semaphore,
    model_name: str,
) -> EvalResult:
    """Execute + grade one question. Never raises."""
    async with semaphore:
        start = time.perf_counter()
        actual = ""
        error: str | None = None
        try:
            # Use ``chat`` so judge/open-ended prompts get full answers.
            # ``extract`` is lighter but many providers reserve it for
            # JSON-shaped output. Chat is the safe default here.
            system_prompt = (
                "You are a precise, concise tutor. Answer directly without filler."
            )
            content, _usage = await llm_client.chat(
                system_prompt=system_prompt,
                user_message=q.prompt,
            )
            actual = content or ""
        except Exception as exc:  # noqa: BLE001 — per contract
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("LLM call failed for %s: %s", q.id, error)
        latency_ms = int((time.perf_counter() - start) * 1000)

    # Grade
    if error is not None:
        passed = False
    elif q.grade_mode == "judge":
        passed = await grade_answer_judge(
            q.prompt, q.expected, actual, llm_client=llm_client
        )
    else:
        passed = grade_answer(q.expected, actual, q.grade_mode)

    return EvalResult(
        question_id=q.id,
        category=q.category,
        prompt=q.prompt,
        expected=q.expected,
        actual=actual,
        passed=passed,
        grade_mode=q.grade_mode,
        latency_ms=latency_ms,
        model=model_name,
        error=error,
    )


def _aggregate(results: list[EvalResult]) -> tuple[int, int, float, dict[str, float]]:
    """Compute totals + per-category score percentages."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    score_pct = round(100.0 * passed / total, 1) if total else 0.0

    by_cat: dict[str, list[EvalResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    category_scores = {
        cat: round(100.0 * sum(1 for r in rs if r.passed) / len(rs), 1)
        for cat, rs in by_cat.items()
    }
    return passed, failed, score_pct, category_scores


async def run_eval_suite(
    fixture_paths: list[Path],
    *,
    model_hint: str | None = None,
    max_concurrency: int = 5,
) -> EvalReport:
    """Run all questions in ``fixture_paths`` and return an :class:`EvalReport`.

    Args:
        fixture_paths: YAML fixtures with a top-level ``questions:`` key.
        model_hint:    Optional hint passed to ``get_llm_client`` (e.g.
                       ``"fast"`` / ``"large"`` / a concrete provider name).
        max_concurrency: Max concurrent in-flight LLM calls.

    Raises:
        RuntimeError: when no questions could be loaded or no LLM
            provider is available. Per-question failures do NOT raise.
    """
    questions = load_questions(fixture_paths)
    if not questions:
        raise RuntimeError(
            f"No eval questions loaded from fixtures: {fixture_paths}. "
            "Check that the fixture files exist and contain a 'questions:' key."
        )

    # Import lazily so unit tests that monkeypatch the runner don't need
    # the full LLM config stack on import.
    from services.llm.router import get_llm_client

    llm_client = get_llm_client(model_hint)
    model_name = getattr(llm_client, "model", None) or getattr(
        llm_client, "provider_name", "unknown"
    )
    provider_name = getattr(llm_client, "provider_name", "unknown")

    semaphore = asyncio.Semaphore(max_concurrency)
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    results = await asyncio.gather(
        *(_run_one_question(q, llm_client, semaphore, model_name) for q in questions)
    )

    duration_s = round(time.perf_counter() - t0, 2)
    passed, failed, score_pct, cat_scores = _aggregate(results)

    return EvalReport(
        model=str(model_name),
        provider=str(provider_name),
        started_at=started.isoformat().replace("+00:00", "Z"),
        duration_s=duration_s,
        total=len(results),
        passed=passed,
        failed=failed,
        score_pct=score_pct,
        results=results,
        category_scores=cat_scores,
    )
