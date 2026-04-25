"""Service tests for ``services.path_room_factory``.

Covers spec Part F.1 (service-level scenarios) without hitting a real
LLM. Fresh in-memory SQLite per test, mirroring
``tests/scripts/test_path_capstones.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem
from models.user import User
from services import path_room_factory
from services.path_room_factory import (
    GeneratedTask,
    RoomOutline,
    RoomPayload,
    compute_generation_seed,
    generate_and_persist_room,
)


# ── Harness ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite per test (StaticPool keeps it alive)."""

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded_ids(session_factory):
    """Pre-seed user + course + path. Returns (user_id, course_id, path_id)."""

    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    path_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=user_id, name="Factory Tester"))
        db.add(Course(id=course_id, user_id=user_id, name="Course"))
        db.add(
            LearningPath(
                id=path_id,
                slug=f"path-{path_id.hex[:8]}",
                title="Test Path",
                difficulty="beginner",
                track_id="test_track",
            )
        )
        # An existing room+task with matching course_id satisfies the
        # router-level coherence check (not validated by the factory,
        # but realistic test data).
        seed_room_id = uuid.uuid4()
        db.add(
            PathRoom(
                id=seed_room_id,
                path_id=path_id,
                slug="seed-room",
                title="Seed",
                room_order=0,
            )
        )
        db.add(
            PracticeProblem(
                id=uuid.uuid4(),
                course_id=course_id,
                path_room_id=seed_room_id,
                task_order=0,
                question_type="mc",
                question="seed q",
                correct_answer="a",
            )
        )
        await db.commit()
    return user_id, course_id, path_id


# ── Fake LLM client ─────────────────────────────────────────────────


def _outline_payload(title: str = "Iterators 101") -> dict[str, Any]:
    return {
        "title": title,
        "intro_excerpt": (
            "A short intro to iterators in Python — what they are and when to use them."
        ),
        "outcome": "You can write a generator that yields squares.",
        "module_label": "Basics",
        "learning_objectives": [
            "Understand the iterator protocol",
            "Use generator functions",
            "Recognize lazy evaluation",
        ],
    }


def _tasks_payload(task_count: int = 3) -> dict[str, Any]:
    """A valid stage-2 payload with exactly ``task_count`` tasks and one capstone."""

    tasks: list[dict[str, Any]] = []
    for i in range(task_count - 1):
        tasks.append(
            {
                "title": f"Task {i}",
                "question_type": "mc",
                "question": f"What is task {i}?",
                "correct_answer": "yes",
                "explanation": "Because we said so.",
                "hints": ["read carefully", "try a small example"],
                "difficulty_layer": 1,
                "is_capstone": False,
            }
        )
    # Capstone last so the factory's reorder is a no-op for the happy path.
    tasks.append(
        {
            "title": "Capstone",
            "question_type": "code_exercise",
            "question": "Write a generator.",
            "correct_answer": "def gen(): yield 1",
            "explanation": "A generator function uses yield.",
            "hints": ["use yield", "no return needed", "try a for-loop"],
            "difficulty_layer": 2,
            "is_capstone": True,
        }
    )
    return {"tasks": tasks}


class _ScriptedClient:
    """Returns canned strings in order; tracks call count for assertions.

    Each call dequeues the next response. ``model`` is exposed so the
    factory's ``_resolve_model_label`` finds something to persist.
    """

    model = "fake-model-x"

    def __init__(self, responses: list[str | Exception]):
        # Reverse so we can ``pop()`` from the end (cheap O(1)).
        self._responses = list(reversed(responses))
        self.calls: list[tuple[str, str]] = []

    async def extract(
        self, system_prompt: str, user_message: str
    ) -> tuple[str, dict[str, Any]]:
        self.calls.append((system_prompt, user_message))
        if not self._responses:
            raise RuntimeError("scripted client exhausted")
        nxt = self._responses.pop()
        if isinstance(nxt, Exception):
            raise nxt
        return nxt, {"prompt_tokens": 0, "completion_tokens": 0}


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_generation_seed_is_deterministic():
    """Same inputs → same hex; whitespace + case in topic don't matter."""

    user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    path_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    course_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    a = compute_generation_seed(
        user_id=user_id,
        path_id=path_id,
        course_id=course_id,
        topic="Iterators",
        difficulty="beginner",
        task_count=3,
    )
    b = compute_generation_seed(
        user_id=user_id,
        path_id=path_id,
        course_id=course_id,
        topic="  iterators  ",
        difficulty="beginner",
        task_count=3,
    )
    c = compute_generation_seed(
        user_id=user_id,
        path_id=path_id,
        course_id=course_id,
        topic="Iterators",
        difficulty="beginner",
        task_count=4,
    )
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_successful_generation_creates_room_and_tasks(
    session_factory, seeded_ids
):
    """Happy path: outline + tasks resolve cleanly, persist N tasks + 1 room."""

    user_id, course_id, path_id = seeded_ids
    client = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            json.dumps(_tasks_payload(task_count=4)),
        ]
    )

    async with session_factory() as db:
        room = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Iterators",
            difficulty="beginner",
            task_count=4,
            llm_client=client,
        )
        room_id = room.id

    async with session_factory() as db:
        # Exactly one generated PathRoom for this path.
        rooms = (
            (
                await db.execute(
                    sa.select(PathRoom).where(
                        PathRoom.path_id == path_id,
                        PathRoom.room_type == "generated",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rooms) == 1
        persisted = rooms[0]
        assert persisted.id == room_id
        assert persisted.room_type == "generated"
        assert persisted.generated_at is not None
        assert persisted.generation_seed is not None
        assert len(persisted.generation_seed) == 64
        assert persisted.generator_model == "fake-model-x"
        assert persisted.title == "Iterators 101"
        # room_order is 1 because seed_room sits at 0.
        assert persisted.room_order == 1

        tasks = (
            (
                await db.execute(
                    sa.select(PracticeProblem)
                    .where(PracticeProblem.path_room_id == room_id)
                    .order_by(PracticeProblem.task_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(tasks) == 4
        for i, t in enumerate(tasks):
            assert t.task_order == i
            assert t.course_id == course_id
            assert t.source == "ai_generated"
            assert t.problem_metadata is not None
            assert t.problem_metadata["generated_seed"] == persisted.generation_seed
            assert t.problem_metadata["generated_room_title"] == "Iterators 101"
            assert "hints" in t.problem_metadata
            assert "learning_objective" in t.problem_metadata

        # Capstone is the last task (spec Part B.8).
        last = tasks[-1]
        assert last.problem_metadata["is_capstone"] is True
        assert last.question_type == "code_exercise"


@pytest.mark.asyncio
async def test_malformed_json_then_retry_succeeds(session_factory, seeded_ids):
    """One malformed outline response, retry once → succeed."""

    user_id, course_id, path_id = seeded_ids
    client = _ScriptedClient(
        [
            "definitely not json",  # outline attempt 1
            json.dumps(_outline_payload()),  # outline attempt 2
            json.dumps(_tasks_payload(task_count=3)),  # tasks attempt 1
        ]
    )

    async with session_factory() as db:
        room = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Closures",
            difficulty="intermediate",
            task_count=3,
            llm_client=client,
        )

    # 3 LLM calls observed: malformed + retry + tasks.
    assert len(client.calls) == 3
    async with session_factory() as db:
        tasks = (
            (
                await db.execute(
                    sa.select(PracticeProblem).where(
                        PracticeProblem.path_room_id == room.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(tasks) == 3


@pytest.mark.asyncio
async def test_persistence_count_exact(session_factory, seeded_ids):
    """For a 5-task request we expect 5 PracticeProblem rows + 1 PathRoom."""

    user_id, course_id, path_id = seeded_ids
    client = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            json.dumps(_tasks_payload(task_count=5)),
        ]
    )

    async with session_factory() as db:
        room = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Decorators",
            difficulty="intermediate",
            task_count=5,
            llm_client=client,
        )

    async with session_factory() as db:
        room_count = (
            await db.execute(
                sa.select(sa.func.count()).where(
                    PathRoom.path_id == path_id,
                    PathRoom.room_type == "generated",
                )
            )
        ).scalar_one()
        task_count = (
            await db.execute(
                sa.select(sa.func.count()).where(
                    PracticeProblem.path_room_id == room.id
                )
            )
        ).scalar_one()
        assert room_count == 1
        assert task_count == 5


@pytest.mark.asyncio
async def test_idempotent_reuse_by_generation_seed(session_factory, seeded_ids):
    """Second call with identical inputs returns the same room id."""

    user_id, course_id, path_id = seeded_ids
    # First run: full LLM script.
    client1 = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            json.dumps(_tasks_payload(task_count=3)),
        ]
    )
    async with session_factory() as db:
        first = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Generators",
            difficulty="beginner",
            task_count=3,
            llm_client=client1,
        )

    # Second run: empty client. If the factory tries to call the LLM
    # we'd get RuntimeError("scripted client exhausted"). The reuse
    # path must skip LLM entirely.
    client2 = _ScriptedClient([])
    async with session_factory() as db:
        second = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Generators",
            difficulty="beginner",
            task_count=3,
            llm_client=client2,
        )

    assert second.id == first.id
    assert client2.calls == []
    # Only one persisted generated room despite two calls.
    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count()).where(
                    PathRoom.path_id == path_id,
                    PathRoom.room_type == "generated",
                )
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_idempotence_skips_when_seed_is_stale(session_factory, seeded_ids):
    """A seed older than the 1h window does NOT block a new generation.

    Realistic: a user comes back the next day and re-asks for the same
    topic. The previous room is preserved; a fresh one is also created.
    """

    user_id, course_id, path_id = seeded_ids

    # Hand-insert an old "generated" room with the same seed.
    seed_hex = compute_generation_seed(
        user_id=user_id,
        path_id=path_id,
        course_id=course_id,
        topic="Stale Topic",
        difficulty="beginner",
        task_count=3,
    )
    old_room_id = uuid.uuid4()
    old_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    async with session_factory() as db:
        db.add(
            PathRoom(
                id=old_room_id,
                path_id=path_id,
                slug="stale-room",
                title="Stale",
                room_order=99,
                generated_at=old_ts,
                generator_model="old",
                generation_seed=seed_hex,
                room_type="generated",
            )
        )
        await db.commit()

    client = _ScriptedClient(
        [
            json.dumps(_outline_payload(title="Fresh Stale Topic")),
            json.dumps(_tasks_payload(task_count=3)),
        ]
    )
    async with session_factory() as db:
        new = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Stale Topic",
            difficulty="beginner",
            task_count=3,
            llm_client=client,
        )

    assert new.id != old_room_id
    assert new.title == "Fresh Stale Topic"


@pytest.mark.asyncio
async def test_no_partial_state_on_failure(session_factory, seeded_ids):
    """Stage-2 fails twice → no PathRoom, no PracticeProblem written."""

    user_id, course_id, path_id = seeded_ids
    # Outline OK, but tasks always malformed.
    client = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            "junk 1",  # tasks attempt 1
            "junk 2",  # tasks attempt 2 (retry)
        ]
    )

    async with session_factory() as db:
        with pytest.raises(RuntimeError):
            await generate_and_persist_room(
                db,
                user_id=user_id,
                path_id=path_id,
                course_id=course_id,
                topic="Doomed",
                difficulty="intermediate",
                task_count=3,
                llm_client=client,
            )

    async with session_factory() as db:
        # Zero generated rooms persisted.
        gen_count = (
            await db.execute(
                sa.select(sa.func.count()).where(
                    PathRoom.path_id == path_id,
                    PathRoom.room_type == "generated",
                )
            )
        ).scalar_one()
        assert gen_count == 0

        # Practice-problem count for this user/path matches the seed
        # fixture (1) — no new ai_generated rows leaked through.
        ai_count = (
            await db.execute(
                sa.select(sa.func.count()).where(
                    PracticeProblem.course_id == course_id,
                    PracticeProblem.source == "ai_generated",
                )
            )
        ).scalar_one()
        assert ai_count == 0


@pytest.mark.asyncio
async def test_capstone_backfill_runs_after_generation(session_factory, seeded_ids):
    """After generation, ``PathRoom.capstone_problem_ids`` is populated."""

    user_id, course_id, path_id = seeded_ids
    client = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            json.dumps(_tasks_payload(task_count=4)),
        ]
    )

    async with session_factory() as db:
        room = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Iterators",
            difficulty="beginner",
            task_count=4,
            llm_client=client,
        )

    async with session_factory() as db:
        fresh = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room.id))
        ).scalar_one()
        assert fresh.capstone_problem_ids is not None
        assert isinstance(fresh.capstone_problem_ids, list)
        assert len(fresh.capstone_problem_ids) >= 1
        # All ids reference real tasks in this room.
        task_ids = {
            str(t.id)
            for t in (
                (
                    await db.execute(
                        sa.select(PracticeProblem).where(
                            PracticeProblem.path_room_id == room.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        for cap in fresh.capstone_problem_ids:
            assert cap in task_ids


@pytest.mark.asyncio
async def test_module_level_llm_client_override(
    monkeypatch, session_factory, seeded_ids
):
    """``LLM_CLIENT`` module attr is honoured when no kwarg is passed."""

    user_id, course_id, path_id = seeded_ids
    client = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            json.dumps(_tasks_payload(task_count=3)),
        ]
    )
    monkeypatch.setattr(path_room_factory, "LLM_CLIENT", client)

    async with session_factory() as db:
        room = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Closures",
            difficulty="intermediate",
            task_count=3,
        )

    assert room.id is not None
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_capstone_reordered_to_last_when_llm_misorders(
    session_factory, seeded_ids
):
    """If the LLM returns the capstone in the middle, the factory still puts it last."""

    user_id, course_id, path_id = seeded_ids
    # Construct a 3-task payload where the capstone is at index 0.
    # All strings are long enough to pass pydantic min_length checks.
    bad_order = {
        "tasks": [
            {
                "title": "Capstone First",
                "question_type": "code_exercise",
                "question": "Implement the capstone exercise.",
                "correct_answer": "yes",
                "explanation": "Capstone explanation here.",
                "hints": ["hint one", "hint two"],
                "difficulty_layer": 2,
                "is_capstone": True,
            },
            {
                "title": "Easy",
                "question_type": "mc",
                "question": "Is this an easy question?",
                "correct_answer": "yes",
                "explanation": "Yes it is easy.",
                "hints": ["hint one", "hint two"],
                "difficulty_layer": 1,
                "is_capstone": False,
            },
            {
                "title": "Easier",
                "question_type": "mc",
                "question": "Is this an even easier question?",
                "correct_answer": "yes",
                "explanation": "Indeed it is.",
                "hints": ["hint one", "hint two"],
                "difficulty_layer": 1,
                "is_capstone": False,
            },
        ]
    }
    client = _ScriptedClient(
        [
            json.dumps(_outline_payload()),
            json.dumps(bad_order),
        ]
    )

    async with session_factory() as db:
        room = await generate_and_persist_room(
            db,
            user_id=user_id,
            path_id=path_id,
            course_id=course_id,
            topic="Reorder",
            difficulty="beginner",
            task_count=3,
            llm_client=client,
        )

    async with session_factory() as db:
        tasks = (
            (
                await db.execute(
                    sa.select(PracticeProblem)
                    .where(PracticeProblem.path_room_id == room.id)
                    .order_by(PracticeProblem.task_order.asc())
                )
            )
            .scalars()
            .all()
        )
        assert tasks[-1].problem_metadata["is_capstone"] is True
        assert tasks[0].problem_metadata["is_capstone"] is False
        assert tasks[1].problem_metadata["is_capstone"] is False


@pytest.mark.asyncio
async def test_pydantic_outline_rejects_wrong_objective_count():
    """Sanity: ``RoomOutline`` enforces exactly 3 objectives."""

    with pytest.raises(Exception):
        RoomOutline.model_validate(
            {
                "title": "x",
                "intro_excerpt": "a long enough intro string",
                "outcome": "ok",
                "module_label": "ok",
                "learning_objectives": ["one", "two"],
            }
        )


@pytest.mark.asyncio
async def test_pydantic_task_rejects_disallowed_question_type():
    """Sanity: ``GeneratedTask`` rejects ``lab_exercise`` (spec Part B.10)."""

    with pytest.raises(Exception):
        GeneratedTask.model_validate(
            {
                "title": "x",
                "question_type": "lab_exercise",
                "question": "q",
                "correct_answer": "a",
                "explanation": "e",
                "hints": ["a", "b"],
                "difficulty_layer": 1,
                "is_capstone": False,
            }
        )


@pytest.mark.asyncio
async def test_room_payload_capstone_count_validated(monkeypatch):
    """Sanity: 0 or 2+ capstones in a payload trips the validator."""

    from services.path_room_factory import _validate_task_count

    def _task(is_capstone: bool, title: str = "Task title") -> dict[str, Any]:
        return {
            "title": title,
            "question_type": "mc",
            "question": "What is the question here?",
            "correct_answer": "yes",
            "explanation": "Because that is the answer.",
            "hints": ["hint one", "hint two"],
            "difficulty_layer": 1,
            "is_capstone": is_capstone,
        }

    payload_zero = RoomPayload.model_validate({"tasks": [_task(False)]})
    with pytest.raises(ValueError):
        _validate_task_count(payload_zero, 1)

    payload_two = RoomPayload.model_validate(
        {"tasks": [_task(True, "Task one"), _task(True, "Task two")]}
    )
    with pytest.raises(ValueError):
        _validate_task_count(payload_two, 2)
