"""Integration tests for the ``/api/interview/*`` router (Phase 5 T4).

Covers the nine T4 acceptance criteria:

1. ``test_post_start_behavioral_empty_corpus_returns_400`` — corpus gate.
2. ``test_post_start_technical_bypasses_corpus_gate`` — gate scoped to behavioral/mixed.
3. ``test_post_start_mixed_with_2_stories_succeeds`` — corpus gate passes.
4. ``test_post_answer_streams_rubric_and_next_question`` — SSE mid-session.
5. ``test_post_answer_last_turn_streams_completed_with_summary`` — final turn.
6. ``test_get_session_rehydrates_full_state`` — pause/resume.
7. ``test_post_abandon_sets_completed_early`` — end-early.
8. ``test_post_save_gaps_creates_interview_cards`` — save-gaps spawns cards.
9. ``test_rate_limit_6_per_day_returns_429`` — rate-limit bucket.

Every test monkeypatches ``InterviewerAgent`` on the router module so no
real LLM call is issued. The content-file gate is tested by pointing the
router at a throwaway text via ``monkeypatch.setattr(..., "CONTENT_DIR",
tmp_path)`` on the router's imported ``CONTENT_DIR`` — we don't mutate the
real ``content/`` directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from schemas.interview import DimensionScore, RubricScores
from services.agent.agents.interviewer import InterviewerAgent


# ── Fake corpus text ────────────────────────────────────────────────

# A "filled" story — low TODO density in the Action+Result block. Two
# of these give us a corpus that passes the _MIN_FILLED_STORIES=2 gate.
_FILLED_STORY = """## Story {n} — Shipped a thing

**Project:** `{slug}`

**S (Situation):**
> Concrete context.

**T (Task):**
> Concrete task.

**A (Action):**
> Picked CLIP ViT-B/32 because 512-dim fits FAISS flat-IP at 150k items.
> Translated UA queries to EN via Groq llama-3.3-70b before embedding.
> Stored thumbnails on disk; B64 in SQLite was too slow.

**R (Result):**
> p95 query latency 120ms; wife's workflow dropped from 30 min to 4 min.
"""

# TODO-heavy story — triggers the corpus-empty gate when repeated.
_EMPTY_STORY = """## Story {n} — Built a thing

**S:** _TODO: fill_

**A (Action):**
> _TODO: fill_
> _TODO: fill_
> _TODO: fill_

**R (Result):**
> _TODO: fill_
"""


def _make_filled_corpus() -> str:
    """Two filled stories + one TODO-heavy — passes the ≥2 filled gate."""

    return "\n\n".join(
        [
            _FILLED_STORY.format(n=1, slug="3ddepo-search"),
            _FILLED_STORY.format(n=2, slug="content-orchestrator"),
            _EMPTY_STORY.format(n=3),
        ]
    )


def _make_empty_corpus() -> str:
    """Three TODO-heavy stories — fails the gate."""

    return "\n\n".join(_EMPTY_STORY.format(n=i) for i in range(1, 4))


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    """Per-test ``AsyncClient`` with an isolated SQLite DB + isolated content dir.

    Mirrors the fixture in ``test_upload_screenshot.py`` but also points
    the interview router at a tmp content directory so individual tests
    can stage their own corpus text without touching the real repo.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-interview-", suffix=".db")
    os.close(fd)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.test_session_factory = test_session_factory
    original_async_session = database_module.async_session
    database_module.async_session = test_session_factory

    # Start every test with a clean rate-limit bucket so one test's 5
    # starts don't bleed into the next.
    import routers.interview as _iv

    _iv._RATE_LIMIT_STATE.clear()

    # Redirect the router's content dir to tmp_path; tests then write
    # ``star_stories.md`` / ``code_defense_drill.md`` as needed.
    monkeypatch.setattr(_iv, "CONTENT_DIR", tmp_path)
    # Default — empty corpus. Individual tests override with a filled one.
    (tmp_path / "star_stories.md").write_text(_make_empty_corpus(), encoding="utf-8")
    (tmp_path / "code_defense_drill.md").write_text("", encoding="utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, tmp_path

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _create_course(ac: AsyncClient, name: str = "Interview Course") -> str:
    """Bootstrap a course + local user, return the course_id."""

    resp = await ac.post("/api/courses/", json={"name": name, "description": "t"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class _FakeAgent:
    """Stand-in :class:`InterviewerAgent` with scriptable return values.

    Replaces the router's ``_InterviewerAgent`` class binding. Every
    test that needs an LLM call paths through this — the real agent
    is exercised by T3's unit tests instead.
    """

    def __init__(
        self,
        questions: list[dict[str, Any]] | None = None,
        rubrics: list[RubricScores] | None = None,
    ):
        self.questions = list(questions or [])
        self.rubrics = list(rubrics or [])
        self.q_calls = 0
        self.grade_calls = 0

    async def generate_question(self, ctx, **kwargs):
        self.q_calls += 1
        if self.questions:
            return self.questions.pop(0)
        return {
            "question": f"Q{kwargs['turn_number']}?",
            "question_type": kwargs.get("question_type") or "behavioral",
            "grounding_source": "generic",
            "expected_dimensions": ["Situation", "Task", "Action", "Result"],
        }

    async def grade_answer(self, ctx, **kwargs):
        self.grade_calls += 1
        if self.rubrics:
            return self.rubrics.pop(0)
        return _default_rubric()

    def write_summary_inline(self, turns):
        # Delegate to the real implementation so the summary shape
        # matches production — we're not testing the math here, just
        # that the router wires it through.
        from services.agent.agents.interviewer import InterviewerAgent

        return InterviewerAgent().write_summary_inline(turns)


def _default_rubric(score: int = 4) -> RubricScores:
    return RubricScores(
        dimensions={
            d: DimensionScore(score=score, feedback=f"{d} ok")
            for d in ["Situation", "Task", "Action", "Result"]
        },
        feedback_short="Solid answer; tighten the tradeoff section.",
    )


def _install_agent(monkeypatch, agent: _FakeAgent) -> None:
    """Patch the router's ``_InterviewerAgent`` to return ``agent``."""

    import routers.interview as _iv

    monkeypatch.setattr(_iv, "_InterviewerAgent", lambda: agent)


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    agent: InterviewerAgent,
    responses: list[str],
) -> list[dict[str, Any]]:
    """Stub ``agent.get_llm_client`` so the real agent returns scripted JSON."""

    calls: list[dict[str, Any]] = []
    response_iter = iter(responses)

    async def fake_chat(
        system: str,
        user: str,
        images: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, int]]:
        calls.append({"system": system, "user": user, "images": images})
        return next(response_iter), {"input_tokens": 0, "output_tokens": 0}

    fake_client = MagicMock()
    fake_client.chat = fake_chat

    monkeypatch.setattr(agent, "get_llm_client", lambda _ctx=None: fake_client)
    return calls


# ── 1. Corpus-empty gate ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_start_behavioral_empty_corpus_returns_400(client, monkeypatch):
    """TODO-heavy star_stories.md + mode=behavioral → 400 ``content_empty``."""

    ac, tmp_path = client
    # Fixture already wrote an empty corpus; no override needed.
    _install_agent(monkeypatch, _FakeAgent())
    course_id = await _create_course(ac)

    resp = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "behavioral",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    # FastAPI wraps ``HTTPException.detail`` at the top level.
    detail = body.get("detail") if isinstance(body, dict) else None
    assert isinstance(detail, dict), body
    assert detail.get("error") == "content_empty"
    assert "star_stories.md" in detail.get("cta_url", "")


# ── 1b. Gate is scoped to behavioral/mixed ──────────────────────────


@pytest.mark.asyncio
async def test_post_start_technical_bypasses_corpus_gate(client, monkeypatch):
    """mode=technical + empty stars → 200 (gate guards behavioral/mixed only)."""

    ac, _ = client  # default fixture corpus is empty — leave it alone.
    _install_agent(monkeypatch, _FakeAgent())
    course_id = await _create_course(ac)

    resp = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "technical",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_turns"] == 3
    assert body["turn_number"] == 1


@pytest.mark.asyncio
async def test_post_start_technical_uses_code_defense_grounding_source(
    client, monkeypatch
):
    """Technical start stamps the real code-defense source for LearnDopamine."""

    ac, tmp_path = client
    (tmp_path / "code_defense_drill.md").write_text(
        """
### Project 3: LearnDopamine

- Why OpenTutor base? MIT license, FSRS 4.5 already integrated.
- Why Groq primary? Lower latency for interview turns, OpenAI fallback for reliability.
        """.strip(),
        encoding="utf-8",
    )

    import routers.interview as _iv
    import services.agent.agents.interviewer_prompts as prompts_module

    prompts_module._GROUNDING_CACHE.clear()
    monkeypatch.setattr(prompts_module, "CONTENT_DIR", tmp_path)

    agent = InterviewerAgent()
    _install_fake_llm(
        monkeypatch,
        agent,
        [
            json.dumps(
                {
                    "question": "Why did you choose OpenTutor as the base stack?",
                    "question_type": "technical",
                    "grounding_source": "generic",
                    "expected_dimensions": [
                        "Correctness",
                        "Depth",
                        "Tradeoff",
                        "Clarity",
                    ],
                }
            )
        ],
    )
    monkeypatch.setattr(_iv, "_InterviewerAgent", lambda: agent)
    course_id = await _create_course(ac)

    resp = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "LearnDopamine",
            "mode": "technical",
            "duration": "quick",
            "course_id": course_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounding_source"] == "code_defense_drill.md#project-3"
    assert "OpenTutor" in body["question"]


# ── 1c. Mixed with 2 filled stories — gate opens ────────────────────


@pytest.mark.asyncio
async def test_post_start_mixed_with_2_stories_succeeds(client, monkeypatch):
    """≥2 filled stories + mode=mixed + duration=quick → 200."""

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")
    _install_agent(monkeypatch, _FakeAgent())
    course_id = await _create_course(ac)

    resp = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "mixed",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_turns"] == 3
    assert body["turn_number"] == 1


# ── 2. Happy path: quick/3q start ───────────────────────────────────


@pytest.mark.asyncio
async def test_post_start_quick_3q_creates_session_and_first_turn(client, monkeypatch):
    """Filled corpus + quick → 200 with total_turns=3 and turn 1 persisted."""

    ac, tmp_path = client
    # Override the default (empty) corpus with a filled one.
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    agent = _FakeAgent(
        questions=[
            {
                "question": "Walk me through 3ddepo-search FAISS choice.",
                "question_type": "technical",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Correctness", "Depth", "Tradeoff", "Clarity"],
            }
        ]
    )
    _install_agent(monkeypatch, agent)

    course_id = await _create_course(ac)

    resp = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "behavioral",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["total_turns"] == 3
    assert payload["turn_number"] == 1
    assert "FAISS" in payload["question"]
    assert "star_stories.md" in payload["grounding_source"]
    session_id = payload["session_id"]

    # Rehydrate to confirm 1 turn is persisted with no answer yet.
    state_resp = await ac.get(f"/api/interview/{session_id}")
    assert state_resp.status_code == 200, state_resp.text
    state = state_resp.json()
    assert state["status"] == "in_progress"
    assert state["total_turns"] == 3
    assert len(state["turns"]) == 1
    assert state["turns"][0]["answer"] is None
    assert state["turns"][0]["rubric"] is None
    assert state["turns"][0]["question_type"] == "technical"


# ── 3. SSE answer — rubric then next_question ───────────────────────


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """Split an SSE body into ``(event_name, data_dict)`` tuples.

    Enough SSE for our tests — we don't need comments or multi-line data.
    """

    events: list[tuple[str, dict[str, Any]]] = []
    current_event: str | None = None
    current_data: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            if current_event and current_data:
                data = "\n".join(current_data)
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    parsed = {"_raw": data}
                events.append((current_event, parsed))
            current_event = None
            current_data = []
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:") :].strip())
    # Final event without trailing blank line.
    if current_event and current_data:
        data = "\n".join(current_data)
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = {"_raw": data}
        events.append((current_event, parsed))
    return events


@pytest.mark.asyncio
async def test_post_answer_streams_rubric_and_next_question(client, monkeypatch):
    """Mid-session answer → SSE ``rubric`` → ``next_question``."""

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    agent = _FakeAgent(
        questions=[
            {
                "question": "Q1 — why FAISS?",
                "question_type": "technical",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Correctness", "Depth", "Tradeoff", "Clarity"],
            },
            {
                "question": "Q2 — tell me about a tradeoff.",
                "question_type": "behavioral",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Situation", "Task", "Action", "Result"],
            },
        ],
        rubrics=[_default_rubric(score=4)],
    )
    _install_agent(monkeypatch, agent)

    course_id = await _create_course(ac)

    start = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "mixed",
            "duration": "standard",  # 10 turns — plenty of headroom
            "course_id": course_id,
        },
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["session_id"]

    resp = await ac.post(
        f"/api/interview/{session_id}/answer",
        json={"answer_text": "FAISS flat-IP at 150k fits in RAM; HNSW overkill."},
    )
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)
    names = [e[0] for e in events]
    assert "rubric" in names
    assert "next_question" in names

    rubric_event = next(e for e in events if e[0] == "rubric")[1]
    assert rubric_event["turn_number"] == 1
    assert "dimensions" in rubric_event
    assert set(rubric_event["dimensions"].keys()) == {
        "Situation",
        "Task",
        "Action",
        "Result",
    }

    next_q_event = next(e for e in events if e[0] == "next_question")[1]
    assert next_q_event["turn_number"] == 2
    assert "tradeoff" in next_q_event["question"].lower()


# ── 4. SSE answer — last turn completes with summary ────────────────


@pytest.mark.asyncio
async def test_post_answer_last_turn_streams_completed_with_summary(
    client, monkeypatch
):
    """3rd POST on a 3-turn session → SSE ``rubric`` → ``completed`` with summary."""

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    # Pre-stage 3 questions + 3 rubrics so each of the three POSTs
    # consumes one of each.
    agent = _FakeAgent(
        questions=[
            {
                "question": f"Q{i}?",
                "question_type": "behavioral",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Situation", "Task", "Action", "Result"],
            }
            for i in range(1, 4)
        ],
        rubrics=[_default_rubric(score=s) for s in (4, 3, 5)],
    )
    _install_agent(monkeypatch, agent)

    course_id = await _create_course(ac)

    start = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "behavioral",
            "duration": "quick",  # 3 turns
            "course_id": course_id,
        },
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["session_id"]

    # Answers 1 and 2 — advance.
    for i in range(2):
        r = await ac.post(
            f"/api/interview/{session_id}/answer",
            json={"answer_text": f"Answer {i + 1}."},
        )
        assert r.status_code == 200, r.text
        evs = [e[0] for e in _parse_sse(r.text)]
        assert "rubric" in evs
        assert "next_question" in evs

    # Answer 3 — final → ``completed`` with a summary payload.
    final = await ac.post(
        f"/api/interview/{session_id}/answer",
        json={"answer_text": "Last answer."},
    )
    assert final.status_code == 200, final.text
    events = _parse_sse(final.text)
    names = [e[0] for e in events]
    assert "rubric" in names
    assert "completed" in names
    completed = next(e for e in events if e[0] == "completed")[1]
    assert completed["session_id"] == session_id
    summary = completed["summary"]
    # Averaged across 3 graded turns: (4+3+5)/3 = 4.0 per STAR dim.
    for dim in ("Situation", "Task", "Action", "Result"):
        assert summary["avg_by_dimension"][dim] == pytest.approx(4.0)
    assert isinstance(summary["weakest_dimensions"], list)
    assert len(summary["weakest_dimensions"]) == 2

    # And the DB should now reflect status=completed.
    state = (await ac.get(f"/api/interview/{session_id}")).json()
    assert state["status"] == "completed"
    assert state["completed_turns"] == 3


# ── 5. GET rehydrate ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_rehydrates_full_state(client, monkeypatch):
    """Start + 2 graded turns → GET returns both turns with rubrics."""

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    agent = _FakeAgent(
        questions=[
            {
                "question": f"Q{i}?",
                "question_type": "behavioral",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Situation", "Task", "Action", "Result"],
            }
            for i in range(1, 4)
        ],
        rubrics=[_default_rubric(4), _default_rubric(5)],
    )
    _install_agent(monkeypatch, agent)

    course_id = await _create_course(ac)
    start = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "behavioral",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    session_id = start.json()["session_id"]

    # One answer → advance to turn 2; turn 2 stays ungraded.
    await ac.post(f"/api/interview/{session_id}/answer", json={"answer_text": "A1"})

    state_resp = await ac.get(f"/api/interview/{session_id}")
    assert state_resp.status_code == 200, state_resp.text
    state = state_resp.json()

    assert state["status"] == "in_progress"
    assert state["total_turns"] == 3
    assert state["completed_turns"] == 1
    assert state["project_focus"] == "3ddepo-search"
    assert state["mode"] == "behavioral"
    assert len(state["turns"]) == 2

    t1 = state["turns"][0]
    assert t1["turn_number"] == 1
    assert t1["answer"] == "A1"
    assert t1["rubric"] is not None
    assert t1["rubric"]["dimensions"]["Action"]["score"] == 4

    t2 = state["turns"][1]
    assert t2["turn_number"] == 2
    assert t2["answer"] is None
    assert t2["rubric"] is None


# ── 6. Abandon ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_abandon_sets_completed_early(client, monkeypatch):
    """In-progress session with 1 graded turn → abandon → completed_early."""

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    agent = _FakeAgent(
        questions=[
            {
                "question": f"Q{i}?",
                "question_type": "behavioral",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Situation", "Task", "Action", "Result"],
            }
            for i in range(1, 4)
        ],
        rubrics=[_default_rubric(3)],
    )
    _install_agent(monkeypatch, agent)

    course_id = await _create_course(ac)
    start = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "behavioral",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    session_id = start.json()["session_id"]

    # Grade turn 1.
    await ac.post(f"/api/interview/{session_id}/answer", json={"answer_text": "A1"})

    resp = await ac.post(f"/api/interview/{session_id}/abandon")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == session_id
    summary = body["summary"]
    assert summary["avg_by_dimension"]["Situation"] == pytest.approx(3.0)

    state = (await ac.get(f"/api/interview/{session_id}")).json()
    assert state["status"] == "completed_early"
    assert state["summary"] is not None


# ── 6b. Save-gaps — creates interview-origin flashcards ─────────────


@pytest.mark.asyncio
async def test_post_save_gaps_creates_interview_cards(client, monkeypatch):
    """Completed 3-turn session + 2 turn ids → 2 interview-origin cards."""

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    agent = _FakeAgent(
        questions=[
            {
                "question": f"Q{i}?",
                "question_type": "behavioral",
                "grounding_source": "star_stories.md#story-1",
                "expected_dimensions": ["Situation", "Task", "Action", "Result"],
            }
            for i in range(1, 4)
        ],
        rubrics=[_default_rubric(s) for s in (4, 3, 5)],
    )
    _install_agent(monkeypatch, agent)

    course_id = await _create_course(ac)
    start = await ac.post(
        "/api/interview/start",
        json={
            "project_focus": "3ddepo-search",
            "mode": "behavioral",
            "duration": "quick",
            "course_id": course_id,
        },
    )
    assert start.status_code == 200, start.text
    session_id = start.json()["session_id"]

    # Complete all 3 turns.
    for i in range(3):
        r = await ac.post(
            f"/api/interview/{session_id}/answer",
            json={"answer_text": f"Answer {i + 1}."},
        )
        assert r.status_code == 200, r.text

    # Fetch the turn IDs directly from the DB fixture — the rehydrate
    # endpoint deliberately only exposes ``turn_number``, so we reach in
    # via the test session factory to pick 2 IDs for the save-gaps call.
    import uuid as _uuid

    from sqlalchemy import select as _select

    from models.interview import InterviewTurn

    async with app.state.test_session_factory() as db:  # type: ignore[attr-defined]
        result = await db.execute(
            _select(InterviewTurn)
            .where(InterviewTurn.session_id == _uuid.UUID(session_id))
            .order_by(InterviewTurn.turn_number.asc())
        )
        turn_ids = [str(t.id) for t in result.scalars().all()]
    assert len(turn_ids) == 3

    save_resp = await ac.post(
        f"/api/interview/{session_id}/save-gaps",
        json={"turn_ids": turn_ids[:2]},
    )
    assert save_resp.status_code == 200, save_resp.text
    body = save_resp.json()
    assert body["saved_count"] == 2
    assert len(body["problem_ids"]) == 2

    # Each row must be tagged as ``interview``-origin and carry the
    # originating session id in problem_metadata.
    from models.practice import PracticeProblem

    async with app.state.test_session_factory() as db:  # type: ignore[attr-defined]
        result = await db.execute(
            _select(PracticeProblem).where(
                PracticeProblem.id.in_([_uuid.UUID(pid) for pid in body["problem_ids"]])
            )
        )
        rows = list(result.scalars().all())
    assert len(rows) == 2
    for pp in rows:
        assert pp.problem_metadata["spawn_origin"] == "interview"
        assert pp.problem_metadata["interview_session_id"] == session_id
        # Card front is prefixed with "Revisit:" so interview cards are
        # visually distinct from chat-spawned ones in ``/due``.
        assert pp.question.startswith("Revisit:")


# ── 7. Rate limit — 6th start in 24h → 429 ──────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_6_per_day_returns_429(client, monkeypatch):
    """5 starts OK, 6th within 24 h → 429.

    Uses a frozen clock so we don't depend on wall-time elapsing.
    """

    ac, tmp_path = client
    (tmp_path / "star_stories.md").write_text(_make_filled_corpus(), encoding="utf-8")

    agent = _FakeAgent()
    _install_agent(monkeypatch, agent)

    import routers.interview as _iv

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(_iv.time, "monotonic", lambda: fake_now["t"])

    course_id = await _create_course(ac)

    payload = {
        "project_focus": "3ddepo-search",
        "mode": "behavioral",
        "duration": "quick",
        "course_id": course_id,
    }

    for i in range(5):
        resp = await ac.post("/api/interview/start", json=payload)
        assert resp.status_code == 200, f"req {i}: {resp.text}"

    # 6th within the window — rejected.
    sixth = await ac.post("/api/interview/start", json=payload)
    assert sixth.status_code == 429, sixth.text
    assert "per day" in sixth.text.lower()

    # Slide the clock forward past 24h — bucket refills.
    fake_now["t"] += _iv._RATE_LIMIT_WINDOW_SEC + 1.0
    seventh = await ac.post("/api/interview/start", json=payload)
    assert seventh.status_code == 200, seventh.text
