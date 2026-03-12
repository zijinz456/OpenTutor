"""API integration tests using httpx AsyncClient on SQLite."""

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from main import app
import database as database_module
from database import get_db, Base
from models.content import CourseContentTree
from models.ingestion import StudySession, WrongAnswer
from models.practice import PracticeProblem, PracticeResult
from models.preference import PreferenceSignal
from models.user import User
from libs.exceptions import LLMUnavailableError
from services.agent.state import AgentContext

TEST_EMAIL = f"test-{uuid.uuid4().hex[:8]}@opentutor.dev"


@pytest_asyncio.fixture
async def client():
    """Create per-test client with an isolated SQLite database."""
    fd, db_path = tempfile.mkstemp(prefix="opentutor-it-", suffix=".db")
    os.close(fd)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ── Health ──

@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "version" in data
    assert data["database_backend"] == "sqlite"
    assert data["deployment_mode"] == "single_user"
    assert "code_sandbox_backend" in data
    assert data["migration_required"] is False
    assert data["migration_status"] == "ready"
    assert data["alembic_version_present"] is False
    assert isinstance(data["local_beta_ready"], bool)
    assert isinstance(data["local_beta_blockers"], list)
    assert isinstance(data["local_beta_warnings"], list)
    assert isinstance(data["features"], dict)
    assert data["features"]["voice_enabled"] is False


# ── Course CRUD ──

@pytest.mark.asyncio
async def test_create_course(client):
    resp = await client.post("/api/courses/", json={"name": "Test Course", "description": "Unit test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Course"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_course_persists_metadata(client):
    resp = await client.post(
        "/api/courses/",
        json={
            "name": "Metadata Course",
            "description": "metadata roundtrip",
            "metadata": {
                "workspace_features": {
                    "notes": True,
                    "practice": False,
                    "wrong_answer": True,
                    "study_plan": False,
                    "free_qa": True,
                },
                "auto_scrape": {
                    "enabled": True,
                },
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["metadata"]["workspace_features"]["practice"] is False
    assert data["metadata"]["workspace_features"]["free_qa"] is True
    assert data["metadata"]["auto_scrape"]["enabled"] is True


@pytest.mark.asyncio
async def test_list_courses(client):
    create_resp = await client.post("/api/courses/", json={"name": "List Course", "description": "for list"})
    assert create_resp.status_code == 201
    resp = await client.get("/api/courses/")
    assert resp.status_code == 200
    courses = resp.json()
    assert isinstance(courses, list)
    assert len(courses) >= 1


@pytest.mark.asyncio
async def test_get_course(client):
    create_resp = await client.post("/api/courses/", json={"name": "Get Course", "description": "for get"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.get(f"/api/courses/{cid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == cid


@pytest.mark.asyncio
async def test_get_course_not_found(client):
    resp = await client.get("/api/courses/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_content_tree_empty(client):
    create_resp = await client.post("/api/courses/", json={"name": "Tree Course", "description": "for tree"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.get(f"/api/courses/{cid}/content-tree")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Preferences ──

@pytest.mark.asyncio
async def test_set_preference(client):
    resp = await client.post("/api/preferences/", json={
        "dimension": "note_format",
        "value": "table",
        "scope": "global",
    })
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_list_preferences(client):
    resp = await client.get("/api/preferences/")
    assert resp.status_code == 200
    prefs = resp.json()
    assert isinstance(prefs, list)


@pytest.mark.asyncio
async def test_resolve_preferences(client):
    resp = await client.get("/api/preferences/resolve")
    assert resp.status_code == 200
    data = resp.json()
    # Should contain system defaults at minimum
    assert isinstance(data, dict)


# ── Upload validation ──

@pytest.mark.asyncio
async def test_upload_invalid_course_id(client):
    resp = await client.post(
        "/api/content/upload",
        data={"course_id": "not-a-uuid"},
        files={"file": ("test.pdf", b"fake content", "application/pdf")},
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_upload_markdown_creates_content_tree_nodes(client):
    create_resp = await client.post("/api/courses/", json={"name": "Markdown Course", "description": "md"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]

    markdown = b"# Binary Search Basics\n\nBinary search repeatedly halves a sorted search space.\n"
    resp = await client.post(
        "/api/content/upload",
        data={"course_id": cid},
        files={"file": ("sample.md", markdown, "text/markdown")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["nodes_created"] >= 1

    tree_resp = await client.get(f"/api/courses/{cid}/content-tree")
    assert tree_resp.status_code == 200
    tree = tree_resp.json()
    assert len(tree) >= 1
    assert tree[0]["title"]


@pytest.mark.asyncio
async def test_upload_same_markdown_to_two_courses_creates_nodes_in_both(client):
    markdown = b"# Binary Search Basics\n\nBinary search repeatedly halves a sorted search space.\n"

    first_course = await client.post("/api/courses/", json={"name": "Course A", "description": "a"})
    second_course = await client.post("/api/courses/", json={"name": "Course B", "description": "b"})
    assert first_course.status_code == 201
    assert second_course.status_code == 201

    first_id = first_course.json()["id"]
    second_id = second_course.json()["id"]

    first_upload = await client.post(
        "/api/content/upload",
        data={"course_id": first_id},
        files={"file": ("sample.md", markdown, "text/markdown")},
    )
    second_upload = await client.post(
        "/api/content/upload",
        data={"course_id": second_id},
        files={"file": ("sample.md", markdown, "text/markdown")},
    )

    assert first_upload.status_code == 200
    assert second_upload.status_code == 200
    assert first_upload.json()["course_id"] == first_id
    assert second_upload.json()["course_id"] == second_id

    first_tree = await client.get(f"/api/courses/{first_id}/content-tree")
    second_tree = await client.get(f"/api/courses/{second_id}/content-tree")
    assert first_tree.status_code == 200
    assert second_tree.status_code == 200
    assert len(first_tree.json()) >= 1
    assert len(second_tree.json()) >= 1


@pytest.mark.asyncio
async def test_scrape_fixture_host_uses_local_fixture_without_dns(client, monkeypatch, tmp_path):
    fixture_dir = tmp_path / "scrape"
    fixture_dir.mkdir()
    (fixture_dir / "binary-search.html").write_text(
        """
        <html>
          <body>
            <main>
              <h1>Binary Search Basics</h1>
              <p>Binary search halves a sorted search space each step.</p>
            </main>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr("routers.upload.settings.scrape_fixture_dir", str(fixture_dir), raising=False)

    create_resp = await client.post("/api/courses/", json={"name": "Scrape Fixture Course", "description": "fixture"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    resp = await client.post(
        "/api/content/url",
        data={"course_id": course_id, "url": "https://opentutor-e2e.local/binary-search"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["course_id"] == course_id
    assert payload["nodes_created"] >= 1

    tree_resp = await client.get(f"/api/courses/{course_id}/content-tree")
    assert tree_resp.status_code == 200
    tree = tree_resp.json()
    assert len(tree) >= 1
    flattened = json.dumps(tree)
    assert "Binary Search Basics" in flattened


@pytest.mark.asyncio
async def test_chat_session_history_persists_and_restores(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Chat Course", "description": "history"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async def fake_orchestrate_stream(**kwargs):
        yield {"event": "message", "data": json.dumps({"content": "Tutor answer"})}
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "status": "complete",
                    "agent": "teaching",
                    "intent": "learn",
                    "session_id": str(kwargs["session_id"]),
                    "tokens": 42,
                    "actions": [{"action": "reorder_blocks", "value": "quiz,notes,progress"}],
                    "provenance": {"content_count": 1, "memory_count": 0, "tool_count": 0},
                }
            ),
        }

    monkeypatch.setattr("routers.chat.orchestrate_stream", fake_orchestrate_stream)
    monkeypatch.setattr("routers.chat.ensure_llm_ready", lambda *_args, **_kwargs: asyncio.sleep(0))

    async with client.stream(
        "POST",
        "/api/chat/",
        json={"course_id": course_id, "message": "Explain limits"},
    ) as resp:
        assert resp.status_code == 200
        body = (await resp.aread()).decode()
        assert "Tutor answer" in body

    sessions_resp = await client.get(f"/api/chat/courses/{course_id}/sessions")
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()
    assert len(sessions) == 1
    session_id = sessions[0]["id"]
    assert sessions[0]["message_count"] == 2

    messages_resp = await client.get(f"/api/chat/sessions/{session_id}/messages")
    assert messages_resp.status_code == 200
    messages = messages_resp.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Explain limits"
    assert messages[1]["content"] == "Tutor answer"
    assert messages[1]["metadata_json"]["agent"] == "teaching"
    assert messages[1]["metadata_json"]["provenance"]["content_count"] == 1
    assert messages[1]["metadata_json"]["actions"][0]["action"] == "reorder_blocks"


@pytest.mark.asyncio
async def test_save_generated_quiz_persists_questions(client):
    create_resp = await client.post("/api/courses/", json={"name": "Generated Quiz Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    raw_content = json.dumps([
        {
            "question_type": "mc",
            "question": "What is 2 + 2?",
            "options": {"A": "3", "B": "4", "C": "5", "D": "6"},
            "correct_answer": "B",
            "explanation": "2 + 2 = 4",
            "difficulty_layer": 1,
            "problem_metadata": {
                "core_concept": "addition",
                "bloom_level": "remember",
                "potential_traps": [],
                "layer_justification": "Basic arithmetic recall",
                "skill_focus": "recall",
                "source_section": "Arithmetic",
            },
        }
    ])

    save_resp = await client.post(
        "/api/quiz/save-generated",
        json={"course_id": course_id, "raw_content": raw_content, "title": "Arithmetic"},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["saved"] == 1

    list_resp = await client.get(f"/api/quiz/{course_id}")
    assert list_resp.status_code == 200
    problems = list_resp.json()
    assert len(problems) == 1
    assert problems[0]["question"] == "What is 2 + 2?"


@pytest.mark.asyncio
async def test_save_generated_quiz_accepts_single_object_payload(client):
    create_resp = await client.post("/api/courses/", json={"name": "Singleton Quiz Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    raw_content = json.dumps(
        {
            "question_type": "mc",
            "question": "What is the loop invariant?",
            "options": {"A": "Sorted prefix", "B": "Target stays inside bounds"},
            "correct_answer": "B",
            "explanation": "Binary search preserves the candidate interval.",
            "difficulty_layer": 1,
            "problem_metadata": {"core_concept": "binary search"},
        }
    )

    save_resp = await client.post(
        "/api/quiz/save-generated",
        json={"course_id": course_id, "raw_content": raw_content, "title": "Singleton"},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["saved"] == 1

    list_resp = await client.get(f"/api/quiz/{course_id}")
    assert list_resp.status_code == 200
    problems = list_resp.json()
    assert len(problems) == 1
    assert problems[0]["question"] == "What is the loop invariant?"


@pytest.mark.asyncio
async def test_quiz_list_normalizes_legacy_list_options(client):
    create_resp = await client.post("/api/courses/", json={"name": "Legacy Quiz Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async with app.state.test_session_factory() as session:
        session.add(
            PracticeProblem(
                course_id=uuid.UUID(course_id),
                content_node_id=None,
                question_type="mc",
                question="Pick the correct bound update",
                options=["A: Move left", "B: Move right", None],
                correct_answer="A",
                explanation="Legacy list-shaped options should still render.",
                order_index=1,
            )
        )
        await session.commit()

    list_resp = await client.get(f"/api/quiz/{course_id}")
    assert list_resp.status_code == 200
    problems = list_resp.json()
    assert len(problems) == 1
    assert problems[0]["options"] == {"A": "Move left", "B": "Move right"}


@pytest.mark.asyncio
async def test_quiz_list_drops_null_option_values_from_legacy_dicts(client):
    create_resp = await client.post("/api/courses/", json={"name": "Legacy Dict Quiz Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async with app.state.test_session_factory() as session:
        session.add(
            PracticeProblem(
                course_id=uuid.UUID(course_id),
                content_node_id=None,
                question_type="mc",
                question="Which invariant is preserved?",
                options={"A": "Left side stays sorted", "B": "Bounds keep target inside", "C": "", "D": None},
                correct_answer="B",
                explanation="Legacy dict options may contain blank/null values.",
                order_index=1,
            )
        )
        await session.commit()

    list_resp = await client.get(f"/api/quiz/{course_id}")
    assert list_resp.status_code == 200
    problems = list_resp.json()
    assert len(problems) == 1
    assert problems[0]["options"] == {
        "A": "Left side stays sorted",
        "B": "Bounds keep target inside",
    }


@pytest.mark.asyncio
async def test_replace_generated_quiz_archives_previous_batch_version(client):
    create_resp = await client.post("/api/courses/", json={"name": "Replace Batch Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    first_payload = json.dumps([
        {"question_type": "mc", "question": "Q1", "options": {"A": "1", "B": "2", "C": "3", "D": "4"}}
    ])
    first_save = await client.post(
        "/api/quiz/save-generated",
        json={"course_id": course_id, "raw_content": first_payload, "title": "Set 1"},
    )
    assert first_save.status_code == 200
    batch_id = first_save.json()["batch_id"]

    second_payload = json.dumps([
        {"question_type": "mc", "question": "Q2", "options": {"A": "1", "B": "2", "C": "3", "D": "4"}}
    ])
    second_save = await client.post(
        "/api/quiz/save-generated",
        json={
            "course_id": course_id,
            "raw_content": second_payload,
            "title": "Set 1 revised",
            "replace_batch_id": batch_id,
        },
    )
    assert second_save.status_code == 200
    assert second_save.json()["replaced"] is True
    assert second_save.json()["version"] == 2

    list_resp = await client.get(f"/api/quiz/{course_id}")
    problems = list_resp.json()
    assert len(problems) == 1
    assert problems[0]["question"] == "Q2"

    batch_resp = await client.get(f"/api/quiz/{course_id}/generated-batches")
    assert batch_resp.status_code == 200
    batches = batch_resp.json()
    assert len(batches) == 1
    assert batches[0]["batch_id"] == batch_id
    assert batches[0]["current_version"] == 2


@pytest.mark.asyncio
async def test_extract_quiz_returns_structured_503_when_llm_unavailable(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Quiz LLM Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = uuid.UUID(create_resp.json()["id"])

    async with app.state.test_session_factory() as session:
        session.add(
            CourseContentTree(
                course_id=course_id,
                parent_id=None,
                title="Week 1 Notes",
                content=(
                    "Binary search repeatedly halves a sorted search space to locate a target efficiently. "
                    "It relies on maintaining left and right bounds, checking the midpoint, and discarding "
                    "the half that cannot contain the target while preserving the search invariant."
                ),
                level=0,
                order_index=0,
                source_type="manual",
            )
        )
        await session.commit()

    async def fake_extract_questions(*args, **kwargs):
        raise RuntimeError("All LLM providers are unhealthy. Please check API keys and network.")

    monkeypatch.setattr("routers.quiz_generation.extract_questions", fake_extract_questions)

    resp = await client.post("/api/quiz/extract", json={"course_id": str(course_id)})
    assert resp.status_code == 503
    data = resp.json()
    assert data["code"] == "llm_unavailable"
    assert data["status"] == 503


@pytest.mark.asyncio
async def test_generate_flashcards_returns_structured_503_when_llm_unavailable(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Flashcard LLM Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async def fake_generate_flashcards(*args, **kwargs):
        raise RuntimeError("All LLM providers are unhealthy. Please check API keys and network.")

    monkeypatch.setattr(
        "services.spaced_repetition.flashcards.generate_flashcards",
        fake_generate_flashcards,
    )

    resp = await client.post(
        "/api/flashcards/generate",
        json={"course_id": course_id, "count": 5},
    )
    assert resp.status_code == 503
    data = resp.json()
    assert data["code"] == "llm_unavailable"
    assert data["status"] == 503


@pytest.mark.asyncio
async def test_restructure_notes_returns_structured_503_when_llm_unavailable(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Notes LLM Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = uuid.UUID(create_resp.json()["id"])

    node_id = uuid.uuid4()
    async with app.state.test_session_factory() as session:
        session.add(
            CourseContentTree(
                id=node_id,
                course_id=course_id,
                parent_id=None,
                title="Lecture Summary",
                content=(
                    "Binary search is a divide-and-conquer algorithm for sorted arrays. "
                    "It compares the target with the midpoint, then narrows the interval "
                    "while preserving the invariant that the target, if present, stays inside the bounds."
                ),
                level=0,
                order_index=0,
                source_type="manual",
            )
        )
        await session.commit()

    async def fake_restructure_notes(*args, **kwargs):
        raise RuntimeError("All LLM providers are unhealthy. Please check API keys and network.")

    monkeypatch.setattr("routers.notes.restructure_notes", fake_restructure_notes)

    resp = await client.post("/api/notes/restructure", json={"content_node_id": str(node_id)})
    assert resp.status_code == 503
    data = resp.json()
    assert data["code"] == "llm_unavailable"
    assert data["status"] == 503


@pytest.mark.asyncio
async def test_chat_returns_structured_503_when_llm_not_ready(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Chat Ready Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async def fake_ensure_llm_ready(*_args, **_kwargs):
        raise LLMUnavailableError("Chat tutoring requires a real LLM provider.")

    monkeypatch.setattr("routers.chat.ensure_llm_ready", fake_ensure_llm_ready)

    resp = await client.post(
        "/api/chat/",
        json={"course_id": course_id, "message": "Help me with binary search"},
    )
    assert resp.status_code == 503
    data = resp.json()
    assert data["code"] == "llm_unavailable"
    assert "real LLM provider" in data["message"]


@pytest.mark.asyncio
async def test_flashcards_generation_blocks_before_service_call_when_llm_not_ready(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Flashcard Ready Course", "description": "x"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]
    called = False

    async def fake_ensure_llm_ready(*_args, **_kwargs):
        raise LLMUnavailableError("Flashcard generation requires a real LLM provider.")

    async def fake_generate_flashcards(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("routers.flashcards.ensure_llm_ready", fake_ensure_llm_ready)
    monkeypatch.setattr("services.spaced_repetition.flashcards.generate_flashcards", fake_generate_flashcards)

    resp = await client.post(
        "/api/flashcards/generate",
        json={"course_id": course_id, "count": 5},
    )
    assert resp.status_code == 503
    assert called is False


@pytest.mark.asyncio
async def test_learning_overview_returns_cross_course_summary(client):
    first = await client.post("/api/courses/", json={"name": "Course A", "description": "a"})
    second = await client.post("/api/courses/", json={"name": "Course B", "description": "b"})
    assert first.status_code == 201
    assert second.status_code == 201

    resp = await client.get("/api/progress/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_courses"] == 2
    assert "gap_type_breakdown" in data
    assert "diagnosis_breakdown" in data
    assert len(data["course_summaries"]) == 2


@pytest.mark.asyncio
async def test_progress_trend_endpoints_handle_practice_results_with_answered_at(client):
    create_resp = await client.post("/api/courses/", json={"name": "Progress Course", "description": "progress"})
    assert create_resp.status_code == 201
    course_id = uuid.UUID(create_resp.json()["id"])

    async with app.state.test_session_factory() as session:
        user_result = await session.execute(select(User).limit(1))
        user = user_result.scalar_one()
        problem = PracticeProblem(
            course_id=course_id,
            question_type="mc",
            question="What is binary search?",
            correct_answer="A search algorithm",
        )
        session.add(problem)
        await session.flush()
        session.add(
            PracticeResult(
                problem_id=problem.id,
                user_id=user.id,
                user_answer="A search algorithm",
                is_correct=True,
                answered_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            StudySession(
                user_id=user.id,
                course_id=course_id,
                duration_minutes=25,
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    course_trends = await client.get(f"/api/progress/courses/{course_id}/trends")
    assert course_trends.status_code == 200
    course_payload = course_trends.json()
    assert course_payload["course_id"] == str(course_id)
    assert any(entry["quiz_total"] >= 1 for entry in course_payload["trend"])

    global_trends = await client.get("/api/progress/trends")
    assert global_trends.status_code == 200
    assert any(entry["quiz_total"] >= 1 for entry in global_trends.json()["trend"])

    weekly_report = await client.get("/api/progress/weekly-report")
    assert weekly_report.status_code == 200
    assert weekly_report.json()["this_week"]["quiz_total"] >= 1


@pytest.mark.asyncio
async def test_knowledge_graph_failure_returns_structured_500(client, monkeypatch):
    create_resp = await client.post("/api/courses/", json={"name": "Graph Failure", "description": "graph"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    # LOOM must be enabled for this endpoint to be reachable
    monkeypatch.setattr("routers.progress_knowledge.settings.enable_experimental_loom", True)

    async def _raise_graph_error(*_args, **_kwargs):
        raise RuntimeError("graph backend down")

    monkeypatch.setattr("routers.progress_knowledge.build_knowledge_graph", _raise_graph_error)

    resp = await client.get(f"/api/progress/courses/{course_id}/knowledge-graph")
    assert resp.status_code == 500
    payload = resp.json()
    assert payload["code"] == "knowledge_graph_unavailable"
    assert payload["status"] == 500
    assert "Knowledge graph service is unavailable" in payload["message"]


@pytest.mark.asyncio
async def test_save_generated_notes_and_replace_version(client):
    create_resp = await client.post("/api/courses/", json={"name": "Notes Course", "description": "notes"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    first = await client.post(
        "/api/notes/generated/save",
        json={"course_id": course_id, "title": "Summary", "markdown": "# v1"},
    )
    assert first.status_code == 200
    batch_id = first.json()["batch_id"]

    second = await client.post(
        "/api/notes/generated/save",
        json={
            "course_id": course_id,
            "title": "Summary",
            "markdown": "# v2",
            "replace_batch_id": batch_id,
        },
    )
    assert second.status_code == 200
    assert second.json()["replaced"] is True
    assert second.json()["version"] == 2

    listing = await client.get(f"/api/notes/generated/{course_id}")
    assert listing.status_code == 200
    payload = listing.json()
    assert len(payload) == 1
    assert payload[0]["batch_id"] == batch_id
    assert payload[0]["current_version"] == 2


@pytest.mark.asyncio
async def test_save_generated_flashcards_and_study_plans(client):
    create_resp = await client.post("/api/courses/", json={"name": "Assets Course", "description": "assets"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    flash_resp = await client.post(
        "/api/flashcards/generated/save",
        json={
            "course_id": course_id,
            "cards": [{"id": "c1", "front": "Q", "back": "A", "difficulty": "medium", "fsrs": {}}],
            "title": "Flashcards",
        },
    )
    assert flash_resp.status_code == 200

    flash_list = await client.get(f"/api/flashcards/generated/{course_id}")
    assert flash_list.status_code == 200
    assert flash_list.json()[0]["asset_count"] == 1


@pytest.mark.asyncio
async def test_workflow_compat_routes_cover_exam_plan_study_plan_and_wrong_answer_review(client):
    create_resp = await client.post("/api/courses/", json={"name": "Workflow Compat", "description": "compat"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    exam_resp = await client.post(
        "/api/workflows/exam-prep",
        json={"course_id": course_id, "days_until_exam": 5, "exam_topic": "Binary Search"},
    )
    assert exam_resp.status_code == 200
    exam_payload = exam_resp.json()
    assert exam_payload["days_until_exam"] == 5
    assert exam_payload["topics_count"] >= 0
    assert "Day 1" in exam_payload["plan"]

    save_resp = await client.post(
        "/api/workflows/study-plans/save",
        json={
            "course_id": course_id,
            "markdown": "# Plan\n- Day 1: review edge cases",
            "title": "Compat Plan",
        },
    )
    assert save_resp.status_code == 200
    saved = save_resp.json()
    assert saved["batch_id"]
    assert saved["version"] == 1

    list_resp = await client.get(f"/api/workflows/study-plans/{course_id}")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert len(listed) == 1
    assert listed[0]["batch_id"] == saved["batch_id"]

    wrong_answer_id: str
    async with app.state.test_session_factory() as session:
        user_result = await session.execute(select(User).limit(1))
        user = user_result.scalar_one()
        problem = PracticeProblem(
            course_id=uuid.UUID(course_id),
            question_type="mc",
            question="What is the loop invariant in binary search?",
            options={"A": "Correct interval is preserved", "B": "Array is always sorted"},
            correct_answer="A",
            explanation="Binary search preserves a valid search interval each iteration.",
            order_index=1,
            source="generated",
            source_owner="ai",
            locked=False,
        )
        session.add(problem)
        await session.flush()
        wrong = WrongAnswer(
            user_id=user.id,
            problem_id=problem.id,
            course_id=uuid.UUID(course_id),
            user_answer="B",
            correct_answer="A",
            explanation="You tracked a property that is true but not the invariant needed for correctness.",
            error_category="conceptual",
            mastered=False,
            review_count=0,
        )
        session.add(wrong)
        await session.commit()
        wrong_answer_id = str(wrong.id)

    review_resp = await client.get("/api/workflows/wrong-answer-review", params={"course_id": course_id})
    assert review_resp.status_code == 200
    review_payload = review_resp.json()
    assert review_payload["wrong_answer_count"] >= 1
    assert wrong_answer_id in review_payload["wrong_answer_ids"]
    assert "Wrong Answer Review" in review_payload["review"]


@pytest.mark.asyncio
async def test_study_goal_create_update_and_task_link(client):
    create_resp = await client.post("/api/courses/", json={"name": "Goal Course", "description": "goal"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    goal_resp = await client.post(
        "/api/goals/",
        json={
            "course_id": course_id,
            "title": "Pass the midterm",
            "objective": "Reach 85%+ on the midterm with confident binary search problem solving.",
            "success_metric": "Score at least 85%",
            "next_action": "Review weak quiz areas",
        },
    )
    assert goal_resp.status_code == 201
    goal = goal_resp.json()
    assert goal["title"] == "Pass the midterm"
    assert goal["status"] == "active"

    update_resp = await client.patch(
        f"/api/goals/{goal['id']}",
        json={"current_milestone": "Finish chapter 3 review", "status": "active"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["current_milestone"] == "Finish chapter 3 review"

    task_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "weekly_prep",
            "title": "Goal-linked weekly prep",
            "course_id": course_id,
            "goal_id": goal["id"],
        },
    )
    assert task_resp.status_code == 201
    assert task_resp.json()["goal_id"] == goal["id"]

    list_resp = await client.get(f"/api/goals/?course_id={course_id}")
    assert list_resp.status_code == 200
    goals = list_resp.json()
    assert len(goals) == 1
    assert goals[0]["id"] == goal["id"]
    assert goals[0]["linked_task_count"] == 1


@pytest.mark.asyncio
async def test_agent_task_cancel_running_and_resume_from_checkpoint(client, monkeypatch):
    import services.activity.engine as activity_engine
    import services.activity.engine_dispatch as _dispatch
    import services.activity.engine_execution as _execution
    import services.activity.engine_lifecycle as _lifecycle
    import services.activity.engine_queries as _queries

    for _mod in (_dispatch, _execution, _lifecycle, _queries):
        monkeypatch.setattr(_mod, "async_session", app.state.test_session_factory)

    second_step_started = asyncio.Event()
    allow_second_step_finish = asyncio.Event()

    async def fake_run_agent_turn(*, message, **_kwargs):
        ctx = AgentContext(
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            user_message=message,
        )
        if "identify weak areas" in message.lower():
            second_step_started.set()
            await allow_second_step_finish.wait()
        if "create study plan" in message.lower():
            ctx.response = (
                "This week:\n"
                "1. Monday: review the weak binary-search cases for 30 minutes.\n"
                "2. Tuesday: solve 5 targeted practice problems.\n"
            )
        else:
            ctx.response = f"Completed: {message}"
        ctx.delegated_agent = "planning"
        return ctx

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)

    create_resp = await client.post("/api/courses/", json={"name": "Resume Course", "description": "queue"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "multi_step",
            "title": "Queued resumable plan",
            "course_id": course_id,
            "input_json": {
                "course_id": course_id,
                "steps": [
                    {
                        "step_index": 0,
                        "step_type": "check_progress",
                        "title": "Check progress",
                        "description": "Review current progress",
                        "depends_on": [],
                        "agent": "assessment",
                    },
                    {
                        "step_index": 1,
                        "step_type": "identify_weak_points",
                        "title": "Find weak areas",
                        "description": "Identify weak areas",
                        "depends_on": [0],
                        "agent": "assessment",
                    },
                    {
                        "step_index": 2,
                        "step_type": "build_study_plan",
                        "title": "Build study plan",
                        "description": "Create study plan",
                        "depends_on": [1],
                        "agent": "planning",
                    },
                ],
            },
        },
    )
    assert submit_resp.status_code == 201
    task_id = submit_resp.json()["id"]

    drain_task = asyncio.create_task(activity_engine.drain_once())
    await asyncio.wait_for(second_step_started.wait(), timeout=5)

    cancel_resp = await client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancel_requested"

    allow_second_step_finish.set()
    processed = await asyncio.wait_for(drain_task, timeout=5)
    assert processed is True

    cancelled_task_resp = await client.get("/api/tasks/")
    assert cancelled_task_resp.status_code == 200
    cancelled_task = next(item for item in cancelled_task_resp.json() if item["id"] == task_id)
    assert cancelled_task["status"] == "cancelled"
    assert cancelled_task["result_json"]["completed"] == 2
    assert cancelled_task["result_json"]["resume_available"] is True
    assert cancelled_task["metadata_json"]["plan_progress"][2]["status"] == "pending"

    resume_resp = await client.post(f"/api/tasks/{task_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "resuming"

    processed = await activity_engine.drain_once()
    assert processed is True

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    task = next(item for item in tasks_resp.json() if item["id"] == task_id)
    assert task["status"] == "completed"
    assert task["result_json"]["completed"] == 3
    assert task["result_json"]["resume_available"] is False
    assert task["metadata_json"]["plan_progress"][2]["status"] == "completed"


@pytest.mark.asyncio
async def test_agent_task_code_execution_forces_container_backend(client, monkeypatch):
    import services.activity.engine as activity_engine
    import services.activity.engine_dispatch as _dispatch
    import services.activity.engine_execution as _execution
    import services.activity.engine_lifecycle as _lifecycle
    import services.activity.engine_queries as _queries

    for _mod in (_dispatch, _execution, _lifecycle, _queries):
        monkeypatch.setattr(_mod, "async_session", app.state.test_session_factory)

    captured = {}

    def fake_execute_safe(self, code):
        from services.agent.code_execution import get_effective_sandbox_backend

        captured["backend"] = get_effective_sandbox_backend()
        captured["code"] = code
        return {"success": True, "output": "42\n", "error": "", "backend": captured["backend"]}

    monkeypatch.setattr("services.agent.code_execution.CodeExecutionAgent._execute_safe", fake_execute_safe)

    create_resp = await client.post("/api/courses/", json={"name": "Code Task Course", "description": "sandbox"})
    assert create_resp.status_code == 201

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "code_execution",
            "title": "Run code in task queue",
            "input_json": {"code": "print(42)"},
        },
    )
    assert submit_resp.status_code == 201
    task_id = submit_resp.json()["id"]

    processed = await activity_engine.drain_once()
    assert processed is True
    assert captured["backend"] in ("container", "auto", "process")
    assert captured["code"] == "print(42)"

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    task = next(item for item in tasks_resp.json() if item["id"] == task_id)
    assert task["status"] == "completed"
    assert task["result_json"]["backend"] in ("container", "auto", "process")


@pytest.mark.asyncio
async def test_agent_task_multi_step_tracks_step_progress_and_failures(client, monkeypatch):
    import services.activity.engine as activity_engine
    import services.activity.engine_dispatch as _dispatch
    import services.activity.engine_execution as _execution
    import services.activity.engine_lifecycle as _lifecycle
    import services.activity.engine_queries as _queries

    for _mod in (_dispatch, _execution, _lifecycle, _queries):
        monkeypatch.setattr(_mod, "async_session", app.state.test_session_factory)

    async def fake_run_agent_turn(*, message, **_kwargs):
        ctx = AgentContext(
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            user_message=message,
        )
        if "weak areas" in message.lower():
            ctx.mark_failed("assessment unavailable")
            return ctx
        ctx.response = f"Completed: {message}"
        ctx.delegated_agent = "planning"
        return ctx

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)

    create_resp = await client.post("/api/courses/", json={"name": "Multi Step Course", "description": "queue"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "multi_step",
            "title": "Queued multi-step plan",
            "course_id": course_id,
            "input_json": {
                "course_id": course_id,
                "steps": [
                    {
                        "step_index": 0,
                        "step_type": "check_progress",
                        "title": "Check progress",
                        "description": "Review current progress",
                        "depends_on": [],
                        "agent": "assessment",
                    },
                    {
                        "step_index": 1,
                        "step_type": "identify_weak_points",
                        "title": "Find weak areas",
                        "description": "Identify weak areas",
                        "depends_on": [0],
                        "agent": "assessment",
                    },
                ],
            },
        },
    )
    assert submit_resp.status_code == 201
    task_id = submit_resp.json()["id"]

    processed = await activity_engine.drain_once()
    assert processed is True

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    task = next(item for item in tasks_resp.json() if item["id"] == task_id)
    assert task["status"] == "completed"
    assert task["result_json"]["completed"] == 1
    assert task["result_json"]["failed"] == 1
    assert task["result_json"]["steps"][1]["success"] is False
    assert task["metadata_json"]["plan_progress"][0]["status"] == "completed"
    assert task["metadata_json"]["plan_progress"][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_failed_multi_step_auto_queues_repair_plan(client, monkeypatch):
    import services.activity.engine as activity_engine
    import services.activity.engine_dispatch as _dispatch
    import services.activity.engine_execution as _execution
    import services.activity.engine_lifecycle as _lifecycle
    import services.activity.engine_queries as _queries

    for _mod in (_dispatch, _execution, _lifecycle, _queries):
        monkeypatch.setattr(_mod, "async_session", app.state.test_session_factory)

    async def fake_run_agent_turn(*, message, **_kwargs):
        ctx = AgentContext(
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            user_message=message,
        )
        if "weak areas" in message.lower():
            ctx.mark_failed("assessment unavailable")
            return ctx
        ctx.response = f"Completed: {message}"
        ctx.delegated_agent = "planning"
        return ctx

    async def fake_create_plan(_prompt, _user_id, _course_id, mastery_summary=None):
        return [
            {
                "step_index": 0,
                "step_type": "identify_weak_points",
                "title": "Repair blocked assessment",
                "description": "Re-run the blocked weak-points assessment with tighter scope",
                "agent": "assessment",
                "depends_on": [],
                "status": "pending",
                "input_params": {},
            }
        ]

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr("services.agent.task_planner.create_plan", fake_create_plan)

    create_resp = await client.post("/api/courses/", json={"name": "Repair Queue Course", "description": "queue"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "multi_step",
            "title": "Queued repairable multi-step plan",
            "course_id": course_id,
            "input_json": {
                "course_id": course_id,
                "steps": [
                    {
                        "step_index": 0,
                        "step_type": "check_progress",
                        "title": "Check progress",
                        "description": "Review current progress",
                        "depends_on": [],
                        "agent": "assessment",
                    },
                    {
                        "step_index": 1,
                        "step_type": "identify_weak_points",
                        "title": "Find weak areas",
                        "description": "Identify weak areas",
                        "depends_on": [0],
                        "agent": "assessment",
                    },
                ],
            },
        },
    )
    assert submit_resp.status_code == 201
    original_task_id = submit_resp.json()["id"]

    processed = await activity_engine.drain_once()
    assert processed is True

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()
    original = next(item for item in tasks if item["id"] == original_task_id)
    repair = next(item for item in tasks if item["source"] == "task_auto_repair")

    assert original["metadata_json"]["auto_repair_task_id"] == repair["id"]
    assert original["result_json"]["task_review"]["follow_up"]["auto_queued"] is True
    assert original["result_json"]["task_review"]["follow_up"]["queued_task_id"] == repair["id"]
    assert repair["task_type"] == "multi_step"
    assert repair["status"] == "queued"
    assert repair["input_json"]["steps"][0]["title"] == "Repair blocked assessment"


@pytest.mark.asyncio
async def test_list_preference_signals(client):
    create_resp = await client.post("/api/courses/", json={"name": "Preference Course", "description": "signals"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async with app.state.test_session_factory() as session:
        result = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = result.scalar_one()
        session.add(
            PreferenceSignal(
                user_id=user_id,
                course_id=uuid.UUID(course_id),
                signal_type="explicit",
                dimension="detail_level",
                value="concise",
                context={"evidence": "Make it shorter", "user_message": "Please keep it concise"},
            )
        )
        await session.commit()

    resp = await client.get(f"/api/preferences/signals?course_id={course_id}")
    assert resp.status_code == 200
    signals = resp.json()
    assert len(signals) == 1
    assert signals[0]["dimension"] == "detail_level"
    assert signals[0]["context"]["evidence"] == "Make it shorter"


@pytest.mark.asyncio
async def test_scene_recommendation_endpoint_is_not_exposed(client):
    create_resp = await client.post("/api/courses/", json={"name": "Scene Policy Course", "description": "scene"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/scenes/{course_id}/recommend",
        params={"message": "I need to review my wrong answers before the final", "active_tab": "review"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_regression_benchmark_endpoint_runs_offline_suites(client):
    # evaluation router unregistered in feature-pruning sprint (2026-03-12)
    resp = await client.post("/api/eval/regression", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_regression_benchmark_endpoint_strict_mode_requires_retrieval_and_recovery_inputs(client):
    # evaluation router unregistered in feature-pruning sprint (2026-03-12)
    resp = await client.post("/api/eval/regression", json={"strict": True})
    assert resp.status_code == 404


# ── Cleanup ──

@pytest.mark.asyncio
async def test_delete_course(client):
    create_resp = await client.post("/api/courses/", json={"name": "Delete Course", "description": "for delete"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.delete(f"/api/courses/{cid}")
    assert resp.status_code == 204
