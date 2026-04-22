"""Unit tests for ``services.curriculum.syllabus_builder``.

Stub the LLM via ``monkeypatch`` on ``get_llm_client`` — no network calls
to Groq or any real provider. The DB is stubbed with ``AsyncMock`` + fake
content rows, mirroring the pattern in ``tests/test_loom.py``.

Verification criterion (from the plan's techlead T1 row):
"unit test feeds stubbed LLM JSON, asserts parsed nodes + valid topo-sort
path". The happy-path test below exercises both. The remaining tests pin
down the failure modes that make the function trustworthy under real LLM
behaviour: bad JSON, dangling depends_on, invalid topo-sort, retry-then-
success, and both-attempts-fail.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from schemas.curriculum import Syllabus
from services.curriculum import syllabus_builder
from services.curriculum.syllabus_builder import build_syllabus


# ── fixtures / helpers ─────────────────────────────────────


def _row(
    title: str,
    content: str,
    category: str | None = None,
    level: int = 1,
) -> MagicMock:
    """Build a fake ``CourseContentTree`` row with just the fields the
    builder reads. We use ``MagicMock`` so the ORM attribute accesses work
    without instantiating the real model (which would pull in SQLAlchemy
    machinery)."""
    row = MagicMock()
    row.title = title
    row.content = content
    row.content_category = category
    row.level = level
    row.order_index = 0
    return row


def _db_with_rows(rows: list[MagicMock]) -> AsyncMock:
    """Build an ``AsyncSession``-shaped mock whose ``execute`` returns the
    given rows through the same ``.scalars().all()`` chain the production
    code uses."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _valid_syllabus_payload() -> dict[str, Any]:
    """A minimal-but-valid 3-node syllabus with a real prerequisite edge."""
    return {
        "nodes": [
            {
                "slug": "python-basics",
                "topic": "Python Basics",
                "blurb": "Variables, types, and expressions in Python.",
                "depends_on": [],
            },
            {
                "slug": "control-flow",
                "topic": "Control Flow",
                "blurb": "if / while / for statements build on basic syntax.",
                "depends_on": ["python-basics"],
            },
            {
                "slug": "functions",
                "topic": "Functions",
                "blurb": "Defining and calling functions, parameters, returns.",
                "depends_on": ["control-flow"],
            },
        ],
        "suggested_path": ["python-basics", "control-flow", "functions"],
    }


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
) -> list[str]:
    """Replace ``get_llm_client`` so ``client.extract`` returns each
    string in ``responses`` in order. Returns the same list for caller
    inspection."""
    calls: list[str] = []
    response_iter = iter(responses)

    async def fake_extract(system: str, user: str) -> tuple[str, dict[str, Any]]:
        calls.append(user)
        return next(response_iter), {}

    fake_client = MagicMock()
    # AsyncMock isn't needed — fake_extract is already a coroutine fn
    fake_client.extract = fake_extract

    monkeypatch.setattr(
        syllabus_builder, "get_llm_client", lambda _variant=None: fake_client
    )
    return calls


# ── schema-level tests (ensure the validator actually guards what we claim) ──


def test_syllabus_rejects_suggested_path_missing_node() -> None:
    payload = _valid_syllabus_payload()
    payload["suggested_path"] = payload["suggested_path"][:-1]  # drop last
    with pytest.raises(ValidationError):
        Syllabus.model_validate(payload)


def test_syllabus_rejects_bad_topo_sort() -> None:
    payload = _valid_syllabus_payload()
    # swap: put 'functions' before its prerequisite 'control-flow'
    payload["suggested_path"] = ["python-basics", "functions", "control-flow"]
    with pytest.raises(ValidationError):
        Syllabus.model_validate(payload)


def test_syllabus_rejects_dangling_depends_on() -> None:
    payload = _valid_syllabus_payload()
    payload["nodes"][1]["depends_on"] = ["does-not-exist"]
    with pytest.raises(ValidationError):
        Syllabus.model_validate(payload)


def test_syllabus_rejects_self_dependency() -> None:
    payload = _valid_syllabus_payload()
    payload["nodes"][0]["depends_on"] = ["python-basics"]
    with pytest.raises(ValidationError):
        Syllabus.model_validate(payload)


def test_syllabus_rejects_too_few_nodes() -> None:
    payload = _valid_syllabus_payload()
    payload["nodes"] = payload["nodes"][:2]
    payload["suggested_path"] = payload["suggested_path"][:2]
    with pytest.raises(ValidationError):
        Syllabus.model_validate(payload)


def test_syllabus_rejects_bad_slug_pattern() -> None:
    payload = _valid_syllabus_payload()
    payload["nodes"][0]["slug"] = "Python Basics"  # space + uppercase
    payload["suggested_path"][0] = "Python Basics"
    with pytest.raises(ValidationError):
        Syllabus.model_validate(payload)


# ── builder happy path (the T1 verification criterion) ──


@pytest.mark.asyncio
async def test_build_syllabus_returns_parsed_nodes_and_valid_topo_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feed the builder a stubbed LLM JSON response and assert we get back
    a fully parsed ``Syllabus`` whose nodes and topo-sorted path are
    correctly preserved.

    This is the exact criterion the plan's techlead row calls for.
    """
    rows = [
        _row("Chapter 1 — Basics", "A" * 400),
        _row("Chapter 2 — Flow Control", "B" * 400),
        _row("Chapter 3 — Functions", "C" * 400),
    ]
    db = _db_with_rows(rows)
    payload = json.dumps(_valid_syllabus_payload())
    _install_fake_llm(monkeypatch, [payload])

    syllabus = await build_syllabus(db, uuid.uuid4())

    assert syllabus is not None
    assert isinstance(syllabus, Syllabus)
    assert [n.slug for n in syllabus.nodes] == [
        "python-basics",
        "control-flow",
        "functions",
    ]
    assert syllabus.suggested_path == [
        "python-basics",
        "control-flow",
        "functions",
    ]
    # Dependency order is preserved in the path (redundant with Syllabus
    # validator, but asserts the behaviour at the boundary where the user
    # of build_syllabus actually reads it):
    position = {slug: i for i, slug in enumerate(syllabus.suggested_path)}
    for node in syllabus.nodes:
        for dep in node.depends_on:
            assert position[dep] < position[node.slug], (
                f"dependency {dep} should precede {node.slug}"
            )


@pytest.mark.asyncio
async def test_build_syllabus_filters_info_rows_and_short_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``info``-category rows and too-short rows must not reach the prompt.

    We assert via the captured prompt body that only the eligible titles
    leaked into the user prompt.
    """
    rows = [
        _row("Syllabus PDF", "S" * 400, category="syllabus"),  # info -> skip
        _row("Assignment 1", "A" * 400, category="assignment"),  # info -> skip
        _row("Real Chapter", "R" * 400, category="lecture_slides"),  # keep
        _row("Another Chapter", "O" * 400, category="textbook"),  # keep
        _row("Tiny Section", "x" * 30, category="textbook"),  # too short
    ]
    db = _db_with_rows(rows)
    payload = json.dumps(_valid_syllabus_payload())
    prompts = _install_fake_llm(monkeypatch, [payload])

    syllabus = await build_syllabus(db, uuid.uuid4())

    assert syllabus is not None
    assert len(prompts) == 1
    prompt = prompts[0]
    assert "Real Chapter" in prompt
    assert "Another Chapter" in prompt
    assert "Syllabus PDF" not in prompt
    assert "Assignment 1" not in prompt
    assert "Tiny Section" not in prompt


# ── builder failure / retry behaviour ──


@pytest.mark.asyncio
async def test_build_syllabus_retries_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First response is junk; second response is valid — builder should
    return the valid parse and have called the LLM exactly twice."""
    rows = [_row(f"Chapter {i}", "A" * 400) for i in range(3)]
    db = _db_with_rows(rows)
    valid_payload = json.dumps(_valid_syllabus_payload())
    prompts = _install_fake_llm(
        monkeypatch, ["not a json object at all", valid_payload]
    )

    syllabus = await build_syllabus(db, uuid.uuid4())

    assert syllabus is not None
    assert len(syllabus.nodes) == 3
    assert len(prompts) == 2  # retried exactly once


@pytest.mark.asyncio
async def test_build_syllabus_returns_none_after_both_attempts_fail(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If both attempts yield un-parseable responses, builder returns None
    and logs a warning — never raises."""
    rows = [_row(f"Chapter {i}", "A" * 400) for i in range(3)]
    db = _db_with_rows(rows)
    prompts = _install_fake_llm(monkeypatch, ["garbage one", "garbage two"])

    import logging

    caplog.set_level(logging.WARNING, logger="services.curriculum.syllabus_builder")

    syllabus = await build_syllabus(db, uuid.uuid4())

    assert syllabus is None
    assert len(prompts) == 2
    assert any("all 2 attempts failed" in rec.message for rec in caplog.records), (
        "expected a warning log summarising the total failure"
    )


@pytest.mark.asyncio
async def test_build_syllabus_returns_none_when_llm_emits_invalid_topo_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM emits schema-shaped JSON but the suggested_path violates topo
    order. Builder must reject (pydantic validator) and ultimately return
    None after the retry."""
    rows = [_row(f"Chapter {i}", "A" * 400) for i in range(3)]
    db = _db_with_rows(rows)

    bad = _valid_syllabus_payload()
    # functions depends on control-flow, so putting functions first
    # is an illegal topo order.
    bad["suggested_path"] = ["functions", "python-basics", "control-flow"]
    bad_json = json.dumps(bad)
    _install_fake_llm(monkeypatch, [bad_json, bad_json])

    syllabus = await build_syllabus(db, uuid.uuid4())
    assert syllabus is None


@pytest.mark.asyncio
async def test_build_syllabus_returns_none_when_not_enough_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """<2 eligible rows → skip LLM entirely, return None."""
    rows = [_row("Only Chapter", "A" * 400)]
    db = _db_with_rows(rows)
    prompts = _install_fake_llm(monkeypatch, ["should not be called"])

    syllabus = await build_syllabus(db, uuid.uuid4())

    assert syllabus is None
    assert len(prompts) == 0  # LLM never called


@pytest.mark.asyncio
async def test_build_syllabus_strips_markdown_fences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMs love wrapping JSON in ```json fences. The extractor should
    still find the object inside."""
    rows = [_row(f"Chapter {i}", "A" * 400) for i in range(3)]
    db = _db_with_rows(rows)
    payload = _valid_syllabus_payload()
    wrapped = f"```json\n{json.dumps(payload)}\n```"
    _install_fake_llm(monkeypatch, [wrapped])

    syllabus = await build_syllabus(db, uuid.uuid4())
    assert syllabus is not None
    assert len(syllabus.nodes) == 3
