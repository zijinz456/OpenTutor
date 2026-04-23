"""Unit tests for the evaluation harness.

All tests stub the LLM client via ``monkeypatch`` — we never hit a real
provider. That keeps the suite fast and avoids flakes when the
environment has no API key configured.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from schemas.eval import EvalQuestion
from services.eval import runner
from services.eval.grader import grade_answer


# ── grader ───────────────────────────────────────────────────


def test_grade_answer_exact_mode():
    """exact mode: strips + lowercases, accepts/rejects correctly."""
    assert grade_answer("await", "await", "exact") is True
    assert grade_answer("Await", "  AWAIT  ", "exact") is True
    assert grade_answer("await", "awaits", "exact") is False
    assert grade_answer("await", "not the right answer", "exact") is False


def test_grade_answer_regex_mode():
    """regex mode: IGNORECASE | DOTALL, malformed pattern → False."""
    # Simple case-insensitive match
    assert grade_answer("(?i)transformer", "The Transformer paper", "regex") is True
    # DOTALL: '.' crosses newlines
    assert (
        grade_answer(
            "retriev.*generat",
            "retrieve docs\nthen generate answer",
            "regex",
        )
        is True
    )
    # No match → False
    assert grade_answer("(?i)mamba", "transformer architecture", "regex") is False
    # Malformed pattern → False (and does not raise)
    assert grade_answer("(unclosed", "anything", "regex") is False


def test_grade_answer_contains_mode():
    """contains mode: case-insensitive substring check."""
    assert grade_answer("GIL", "the python gil protects state", "contains") is True
    assert grade_answer("cosine", "COSINE similarity is standard", "contains") is True
    assert grade_answer("mutex", "the gil is global", "contains") is False


# ── runner: happy path + failure path ─────────────────────────


def _write_fixture(tmp_path: Path, questions: list[dict[str, Any]]) -> Path:
    """Dump a minimal YAML fixture for the runner to ingest."""
    path = tmp_path / "mini_suite.yaml"
    path.write_text(yaml.safe_dump({"questions": questions}), encoding="utf-8")
    return path


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    chat_impl,
    *,
    model: str = "mock-model",
    provider: str = "mock",
):
    """Monkeypatch the router's ``get_llm_client`` to return a fake."""
    fake = MagicMock()
    fake.chat = chat_impl
    fake.model = model
    fake.provider_name = provider
    monkeypatch.setattr("services.llm.router.get_llm_client", lambda hint=None: fake)
    return fake


@pytest.mark.asyncio
async def test_run_eval_suite_all_pass_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Mock LLM returns the expected answer for each question →
    score_pct == 100.0 and every result.passed is True."""

    questions = [
        {
            "id": "q1",
            "category": "python",
            "prompt": "what keyword?",
            "expected": "await",
            "grade_mode": "contains",
        },
        {
            "id": "q2",
            "category": "ai",
            "prompt": "similarity metric?",
            "expected": "cosine",
            "grade_mode": "contains",
        },
        {
            "id": "q3",
            "category": "ai",
            "prompt": "name architecture",
            "expected": "(?i)transformer",
            "grade_mode": "regex",
        },
    ]
    fixture = _write_fixture(tmp_path, questions)

    async def chat_ok(system_prompt: str, user_message: str, images=None):
        # Reply with text that satisfies each expected pattern.
        if "keyword" in user_message:
            return "The keyword is await.", {}
        if "similarity" in user_message:
            return "Cosine similarity is most common.", {}
        return "We use the Transformer architecture.", {}

    _install_fake_llm(monkeypatch, chat_ok)

    report = await runner.run_eval_suite([fixture])

    assert report.total == 3
    assert report.passed == 3
    assert report.failed == 0
    assert report.score_pct == 100.0
    assert all(r.passed for r in report.results)
    # category_scores populated
    assert report.category_scores["python"] == 100.0
    assert report.category_scores["ai"] == 100.0


@pytest.mark.asyncio
async def test_run_eval_suite_llm_failure_marks_failed_not_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """When the LLM client raises for every question, the suite returns
    a report with passed=False for each — it does not bubble the error."""

    fixture = _write_fixture(
        tmp_path,
        [
            {
                "id": "q1",
                "category": "python",
                "prompt": "anything",
                "expected": "await",
                "grade_mode": "contains",
            },
        ],
    )

    async def chat_boom(system_prompt: str, user_message: str, images=None):
        raise RuntimeError("provider down")

    _install_fake_llm(monkeypatch, chat_boom)

    report = await runner.run_eval_suite([fixture])

    assert report.total == 1
    assert report.passed == 0
    assert report.failed == 1
    assert report.score_pct == 0.0
    assert report.results[0].passed is False
    assert report.results[0].error is not None
    assert "RuntimeError" in report.results[0].error


# ── sanity: fixture loader validates schema ──────────────────


def test_load_questions_parses_fixture(tmp_path: Path):
    """Round-trip: write YAML, load via runner, get EvalQuestion objects."""
    fixture = _write_fixture(
        tmp_path,
        [
            {
                "id": "q1",
                "category": "python",
                "prompt": "p",
                "expected": "await",
            }
        ],
    )
    qs = runner.load_questions([fixture])
    assert len(qs) == 1
    assert isinstance(qs[0], EvalQuestion)
    assert qs[0].grade_mode == "contains"  # default
    assert qs[0].id == "q1"
