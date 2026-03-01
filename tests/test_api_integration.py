"""API integration tests using httpx AsyncClient.

These tests require a PostgreSQL database (auto-created in conftest).
Run with: pytest tests/test_api_integration.py -v
"""

import asyncio
import uuid
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from main import app
from config import settings
from database import get_db, Base
from models.preference import PreferenceSignal
from services.agent.state import AgentContext

TEST_EMAIL = f"test-{uuid.uuid4().hex[:8]}@opentutor.dev"


@pytest_asyncio.fixture
async def client():
    """Create per-test client with an isolated PostgreSQL schema."""
    schema = f"test_{uuid.uuid4().hex[:10]}"
    test_engine = create_async_engine(
        settings.database_url,
        echo=False,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with test_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            pytest.skip(f"pgvector extension unavailable for integration tests: {exc}")
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.test_session_factory = test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await test_engine.dispose()


# ── Health ──

@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


# ── Course CRUD ──

@pytest.mark.asyncio
async def test_create_course(client):
    resp = await client.post("/api/courses/", json={"name": "Test Course", "description": "Unit test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Course"
    assert "id" in data


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
                    "actions": [{"action": "set_layout_preset", "value": "quizFocused"}],
                    "provenance": {"content_count": 1, "memory_count": 0, "tool_count": 0},
                }
            ),
        }

    monkeypatch.setattr("routers.chat.orchestrate_stream", fake_orchestrate_stream)

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
    assert messages[1]["metadata_json"]["actions"][0]["action"] == "set_layout_preset"


@pytest.mark.asyncio
async def test_weekly_prep_creates_agent_task(client, monkeypatch):
    async def fake_run_weekly_prep(_db, _user_id):
        return {
            "plan": "## Weekly Plan\n- Monday: review graphs",
            "next_action": "Monday: review graphs",
            "provenance": {
                "workflow": "weekly_prep",
                "generated": True,
                "source_labels": ["workflow", "generated"],
            },
        }

    monkeypatch.setattr("services.workflow.weekly_prep.run_weekly_prep", fake_run_weekly_prep)

    resp = await client.get("/api/workflows/weekly-prep")
    assert resp.status_code == 200
    assert "Weekly Plan" in resp.json()["plan"]

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()
    assert len(tasks) == 1
    assert tasks[0]["task_type"] == "weekly_prep"
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["metadata_json"]["provenance"]["workflow"] == "weekly_prep"
    assert tasks[0]["metadata_json"]["provenance"]["generated"] is True


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

    plan_resp = await client.post(
        "/api/workflows/study-plans/save",
        json={"course_id": course_id, "markdown": "## Plan", "title": "Exam Plan"},
    )
    assert plan_resp.status_code == 200

    plan_list = await client.get(f"/api/workflows/study-plans/{course_id}")
    assert plan_list.status_code == 200
    assert plan_list.json()[0]["title"] == "Exam Plan"


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
async def test_agent_task_submit_approve_and_drain(client, monkeypatch):
    import services.activity.engine as activity_engine

    create_resp = await client.post("/api/courses/", json={"name": "Async Course", "description": "queue"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    async def fake_exam_prep(db, user_id, course_id, exam_topic=None, days_until_exam=7):
        _ = (db, user_id, course_id, exam_topic, days_until_exam)
        return {"course": "Async Course", "plan": "Queued plan"}

    monkeypatch.setattr("services.workflow.exam_prep.run_exam_prep", fake_exam_prep)
    monkeypatch.setattr(activity_engine, "async_session", app.state.test_session_factory)

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "exam_prep",
            "title": "Queued exam prep",
            "course_id": course_id,
            "input_json": {"course_id": course_id, "days_until_exam": 5},
            "requires_approval": True,
            "max_attempts": 2,
        },
    )
    assert submit_resp.status_code == 201
    task_id = submit_resp.json()["id"]
    assert submit_resp.json()["status"] == "pending_approval"
    assert submit_resp.json()["approval_status"] == "pending"

    approve_resp = await client.post(f"/api/tasks/{task_id}/approve")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "queued"

    processed = await activity_engine.drain_once()
    assert processed is True

    tasks_resp = await client.get(f"/api/tasks/?course_id={course_id}")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()
    assert tasks[0]["id"] == task_id
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["result_json"]["plan"] == "Queued plan"


@pytest.mark.asyncio
async def test_agent_task_reject_then_retry_requires_reapproval(client, monkeypatch):
    import services.activity.engine as activity_engine

    async def fake_exam_prep(db, user_id, course_id, exam_topic=None, days_until_exam=7):
        _ = (db, user_id, course_id, exam_topic, days_until_exam)
        return {"course": "Approval Course", "plan": "Approved after retry"}

    monkeypatch.setattr("services.workflow.exam_prep.run_exam_prep", fake_exam_prep)
    monkeypatch.setattr(activity_engine, "async_session", app.state.test_session_factory)

    create_resp = await client.post("/api/courses/", json={"name": "Approval Course", "description": "queue"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "exam_prep",
            "title": "Approval gated plan",
            "course_id": course_id,
            "input_json": {"course_id": course_id, "days_until_exam": 5},
            "requires_approval": True,
            "max_attempts": 2,
        },
    )
    assert submit_resp.status_code == 201
    task_id = submit_resp.json()["id"]
    assert submit_resp.json()["status"] == "pending_approval"
    assert submit_resp.json()["approval_status"] == "pending"

    reject_resp = await client.post(f"/api/tasks/{task_id}/reject")
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    approve_rejected = await client.post(f"/api/tasks/{task_id}/approve")
    assert approve_rejected.status_code == 409

    retry_resp = await client.post(f"/api/tasks/{task_id}/retry")
    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "pending_approval"
    assert retry_resp.json()["approval_status"] == "pending"
    assert retry_resp.json()["approved_at"] is None

    approve_resp = await client.post(f"/api/tasks/{task_id}/approve")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "queued"

    processed = await activity_engine.drain_once()
    assert processed is True

    tasks_resp = await client.get(f"/api/tasks/?course_id={course_id}")
    assert tasks_resp.status_code == 200
    task = next(item for item in tasks_resp.json() if item["id"] == task_id)
    assert task["status"] == "completed"
    assert task["result_json"]["plan"] == "Approved after retry"


@pytest.mark.asyncio
async def test_agent_task_cancel_and_retry(client, monkeypatch):
    import services.activity.engine as activity_engine

    async def fake_weekly_prep(db, user_id):
        _ = (db, user_id)
        return {"plan": "Rebuilt weekly plan"}

    monkeypatch.setattr("services.workflow.weekly_prep.run_weekly_prep", fake_weekly_prep)
    monkeypatch.setattr(activity_engine, "async_session", app.state.test_session_factory)

    create_resp = await client.post("/api/courses/", json={"name": "Retry Course", "description": "queue"})
    assert create_resp.status_code == 201

    submit_resp = await client.post(
        "/api/tasks/submit",
        json={
            "task_type": "weekly_prep",
            "title": "Queued weekly prep",
            "max_attempts": 1,
        },
    )
    assert submit_resp.status_code == 201
    task_id = submit_resp.json()["id"]
    assert submit_resp.json()["status"] == "queued"

    cancel_resp = await client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    retry_resp = await client.post(f"/api/tasks/{task_id}/retry")
    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "queued"

    processed = await activity_engine.drain_once()
    assert processed is True

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    assert tasks_resp.json()[0]["status"] == "completed"
    assert tasks_resp.json()[0]["result_json"]["plan"] == "Rebuilt weekly plan"


@pytest.mark.asyncio
async def test_agent_task_cancel_running_and_resume_from_checkpoint(client, monkeypatch):
    import services.activity.engine as activity_engine

    monkeypatch.setattr(activity_engine, "async_session", app.state.test_session_factory)

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

    monkeypatch.setattr(activity_engine, "async_session", app.state.test_session_factory)

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
    assert captured["backend"] == "container"
    assert captured["code"] == "print(42)"

    tasks_resp = await client.get("/api/tasks/")
    assert tasks_resp.status_code == 200
    task = next(item for item in tasks_resp.json() if item["id"] == task_id)
    assert task["status"] == "completed"
    assert task["result_json"]["backend"] == "container"


@pytest.mark.asyncio
async def test_agent_task_multi_step_tracks_step_progress_and_failures(client, monkeypatch):
    import services.activity.engine as activity_engine

    monkeypatch.setattr(activity_engine, "async_session", app.state.test_session_factory)

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
async def test_scene_recommendation_endpoint_uses_policy_engine(client):
    create_resp = await client.post("/api/courses/", json={"name": "Scene Policy Course", "description": "scene"})
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/scenes/{course_id}/recommend",
        params={"message": "I need to review my wrong answers before the final", "active_tab": "review"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["scene_id"] in {"review_drill", "exam_prep"}
    assert "reason" in payload
    assert "scores" in payload
    assert "expected_benefit" in payload
    assert "reasoning_policy" in payload


@pytest.mark.asyncio
async def test_regression_benchmark_endpoint_runs_offline_suites(client):
    resp = await client.post("/api/eval/regression", json={})
    assert resp.status_code == 200
    payload = resp.json()
    assert "suites" in payload
    suite_names = {suite["name"] for suite in payload["suites"]}
    assert {"routing", "scene_policy", "retrieval", "response_quality"} <= suite_names
    response_suite = next(suite for suite in payload["suites"] if suite["name"] == "response_quality")
    assert response_suite["skipped"] is False


# ── Cleanup ──

@pytest.mark.asyncio
async def test_delete_course(client):
    create_resp = await client.post("/api/courses/", json={"name": "Delete Course", "description": "for delete"})
    assert create_resp.status_code == 201
    cid = create_resp.json()["id"]
    resp = await client.delete(f"/api/courses/{cid}")
    assert resp.status_code == 204
