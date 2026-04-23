"""Phase 7 guardrails: tests for ``grade_mode: refusal`` + end-to-end run.

Four tests total:

1. ``test_grade_refusal_matches_template_start`` — canonical refusal text.
2. ``test_grade_refusal_case_insensitive`` — lowercased variant.
3. ``test_grade_refusal_rejects_regular_answer`` — grounded answer fails.
4. ``test_run_eval_suite_on_guardrails_fixture`` — integration: runner +
   ``guardrails_smoke.yaml`` with a mock LLM that returns the right thing
   per question category → 100 % pass.

All tests mock the LLM client; no network calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.eval import runner
from services.eval.grader import grade_answer


_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
_GUARDRAILS_FIXTURE = _FIXTURES_DIR / "guardrails_smoke.yaml"


# ── grader unit tests ────────────────────────────────────────


def test_grade_refusal_matches_template_start():
    """Canonical REFUSAL_TEMPLATE text → refusal grade passes."""
    actual = (
        "I don't have this in your course materials. Options:\n"
        "- Paste a URL that covers it\n"
        "- Turn off strict mode for this session"
    )
    assert grade_answer("refusal", actual, "refusal") is True


def test_grade_refusal_case_insensitive():
    """Lowercased refusal text still matches (grader normalizes case)."""
    actual = "i don't have this in your course materials. options: ..."
    assert grade_answer("refusal", actual, "refusal") is True


def test_grade_refusal_rejects_regular_answer():
    """A grounded answer must NOT satisfy refusal grade — that's the point."""
    actual = (
        "await pauses the coroutine until the awaited task completes "
        "and yields control back to the event loop."
    )
    assert grade_answer("refusal", actual, "refusal") is False


# ── integration: runner on the real guardrails fixture ───────


def _install_fake_llm(monkeypatch: pytest.MonkeyPatch, chat_impl):
    """Monkeypatch ``services.llm.router.get_llm_client`` with a fake."""
    fake = MagicMock()
    fake.chat = chat_impl
    fake.model = "mock-model"
    fake.provider_name = "mock"
    monkeypatch.setattr("services.llm.router.get_llm_client", lambda hint=None: fake)
    return fake


@pytest.mark.asyncio
async def test_run_eval_suite_on_guardrails_fixture(
    monkeypatch: pytest.MonkeyPatch,
):
    """End-to-end: mock LLM answers in-corpus questions with content that
    satisfies the regex, and out-of-corpus ones with REFUSAL_TEMPLATE.
    Expected: 10/10 pass, category_scores["guardrails"] == 100.0.
    """

    async def chat_router(system_prompt: str, user_message: str, images=None):
        """Dispatch mock replies by question content."""
        msg = user_message.lower()

        # In-corpus answers — crafted so each question's regex matches.
        if "await" in msg and "async" in msg:
            return (
                "await pauses the current coroutine and yields control to "
                "the event loop until the awaited task completes.",
                {},
            )
        if "optional type hint" in msg:
            return (
                "Optional[X] is shorthand for Union[X, None] — it marks a "
                "value that can be X or None.",
                {},
            )
        if "decorator" in msg:
            return (
                "A decorator is a callable that wraps another function to "
                "modify or extend its behavior without changing its source.",
                {},
            )
        if "gil" in msg:
            return (
                "The GIL prevents more than one thread from executing "
                "Python bytecode simultaneously in a single process.",
                {},
            )
        if "list comprehension" in msg:
            return (
                "A list comprehension is used to build a new list by "
                "applying an expression over an iterable in one line.",
                {},
            )

        # Everything else → out-of-corpus → refusal template.
        return (
            "I don't have this in your course materials. Options:\n"
            "- Paste a URL that covers it\n"
            "- Turn off strict mode for this session",
            {},
        )

    _install_fake_llm(monkeypatch, chat_router)

    report = await runner.run_eval_suite([_GUARDRAILS_FIXTURE])

    assert report.total == 10, "fixture should contain 10 questions"
    failures = [(r.question_id, r.actual[:80]) for r in report.results if not r.passed]
    assert report.passed == 10, (
        f"expected all 10 to pass, got {report.passed}; failures: {failures}"
    )
    assert report.failed == 0
    assert report.score_pct == 100.0
    assert report.category_scores["guardrails"] == 100.0
