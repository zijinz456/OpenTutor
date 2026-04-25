from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import LAB_EXERCISE_TYPE, CODE_EXERCISE_TYPE, PracticeProblem
from models.user import User
from scripts.path_capstones import backfill_room_capstones, main


@pytest_asyncio.fixture
async def session_factory():
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


@pytest.mark.asyncio
async def test_backfill_room_capstones_picks_three_hardest_tasks(session_factory):
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    path_id = uuid.uuid4()
    room_id = uuid.uuid4()
    problem_ids = [uuid.uuid4() for _ in range(4)]

    async with session_factory() as db:
        db.add(User(id=user_id, name="Capstone Tester"))
        db.add(Course(id=course_id, user_id=user_id, name="Course"))
        db.add(
            LearningPath(
                id=path_id,
                slug="python-fundamentals",
                title="Python Fundamentals",
                difficulty="beginner",
                track_id="python_fundamentals",
            )
        )
        db.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug="py_intro",
                title="Intro",
                room_order=0,
            )
        )
        db.add_all(
            [
                PracticeProblem(
                    id=problem_ids[0],
                    course_id=course_id,
                    path_room_id=room_id,
                    task_order=0,
                    question_type="mc",
                    question="easy",
                    correct_answer="a",
                    difficulty_layer=1,
                ),
                PracticeProblem(
                    id=problem_ids[1],
                    course_id=course_id,
                    path_room_id=room_id,
                    task_order=1,
                    question_type="trace",
                    question="trace",
                    correct_answer="a",
                    difficulty_layer=2,
                ),
                PracticeProblem(
                    id=problem_ids[2],
                    course_id=course_id,
                    path_room_id=room_id,
                    task_order=2,
                    question_type=CODE_EXERCISE_TYPE,
                    question="code",
                    correct_answer="a",
                    difficulty_layer=2,
                ),
                PracticeProblem(
                    id=problem_ids[3],
                    course_id=course_id,
                    path_room_id=room_id,
                    task_order=3,
                    question_type=LAB_EXERCISE_TYPE,
                    question="lab",
                    correct_answer="a",
                    difficulty_layer=3,
                ),
            ]
        )
        await db.commit()

    async with session_factory() as db:
        updated = await backfill_room_capstones(db)
        await db.commit()
        room = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room_id))
        ).scalar_one()

    assert updated == 1
    assert room.capstone_problem_ids == [
        str(problem_ids[3]),
        str(problem_ids[2]),
        str(problem_ids[1]),
    ]


async def _seed_minimal_room(
    session_factory,
    *,
    room_id: uuid.UUID,
    add_problems: bool = False,
) -> uuid.UUID:
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    path_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=user_id, name="Capstone Tester"))
        db.add(Course(id=course_id, user_id=user_id, name="Course"))
        db.add(
            LearningPath(
                id=path_id,
                slug=f"path-{room_id.hex[:8]}",
                title="Path",
                difficulty="beginner",
                track_id="t",
            )
        )
        db.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug="room",
                title="Room",
                room_order=0,
            )
        )
        if add_problems:
            db.add_all(
                [
                    PracticeProblem(
                        id=uuid.uuid4(),
                        course_id=course_id,
                        path_room_id=room_id,
                        task_order=i,
                        question_type=qtype,
                        question="q",
                        correct_answer="a",
                        difficulty_layer=layer,
                    )
                    for i, (qtype, layer) in enumerate(
                        [("mc", 1), (CODE_EXERCISE_TYPE, 2), (LAB_EXERCISE_TYPE, 3)]
                    )
                ]
            )
        await db.commit()
    return course_id


@pytest.mark.asyncio
async def test_backfill_empty_room_does_not_crash(session_factory):
    room_id = uuid.uuid4()
    await _seed_minimal_room(session_factory, room_id=room_id, add_problems=False)

    async with session_factory() as db:
        updated = await backfill_room_capstones(db)
        await db.commit()
        room = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room_id))
        ).scalar_one()

    assert updated == 0
    assert room.capstone_problem_ids is None


@pytest.mark.asyncio
async def test_backfill_rerun_is_noop(session_factory):
    room_id = uuid.uuid4()
    await _seed_minimal_room(session_factory, room_id=room_id, add_problems=True)

    async with session_factory() as db:
        first = await backfill_room_capstones(db)
        await db.commit()
    async with session_factory() as db:
        second = await backfill_room_capstones(db)
        await db.commit()
        room = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room_id))
        ).scalar_one()

    assert first == 1
    assert second == 0
    assert room.capstone_problem_ids is not None
    assert len(room.capstone_problem_ids) == 3


@pytest.mark.asyncio
async def test_main_dry_run_does_not_persist(session_factory):
    room_id = uuid.uuid4()
    await _seed_minimal_room(session_factory, room_id=room_id, add_problems=True)

    rc = await main(dry_run=True, session_factory=session_factory)

    async with session_factory() as db:
        room = (
            await db.execute(sa.select(PathRoom).where(PathRoom.id == room_id))
        ).scalar_one()

    assert rc == 0
    assert room.capstone_problem_ids is None
