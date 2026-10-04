"""DB-level foreign key ondelete tests (issue #36).

Uses a real SQLite database (aiosqlite) with PRAGMA foreign_keys=ON and
Core DELETE statements (no ORM relationship cascade) so the assertions
exercise the actual ondelete rules emitted by Base.metadata.create_all().
"""

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models.content import CourseContentTree
from models.course import Course
from models.chat_session import ChatSession
from models.generated_asset import GeneratedAsset
from models.memory import ConversationMemory
from models.practice import PracticeProblem, PracticeResult
from models.usage_event import UsageEvent
from models.user import User


@pytest_asyncio.fixture
async def session_factory():
    """Isolated SQLite database with foreign key enforcement enabled."""
    fd, db_path = tempfile.mkstemp(prefix="opentutor-fk-", suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fks(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _seed_user_graph(session):
    """Create a user with a course, memory, practice result, chat session, usage event."""
    user = User(name="FK Test User")
    session.add(user)
    await session.flush()

    course = Course(user_id=user.id, name="FK Test Course")
    session.add(course)
    await session.flush()

    problem = PracticeProblem(course_id=course.id, question_type="mc", question="2+2?")
    session.add(problem)
    await session.flush()

    session.add_all(
        [
            ConversationMemory(user_id=user.id, course_id=course.id, summary="remembers things"),
            PracticeResult(problem_id=problem.id, user_id=user.id, user_answer="4", is_correct=True),
            ChatSession(user_id=user.id, course_id=course.id),
            UsageEvent(
                user_id=user.id,
                course_id=course.id,
                model_provider="openai",
                model_name="gpt-test",
            ),
        ]
    )
    await session.commit()
    return user, course, problem


@pytest.mark.asyncio
async def test_delete_user_cascades_owned_records(session_factory):
    async with session_factory() as session:
        user, course, problem = await _seed_user_graph(session)

        # Core DELETE — bypasses ORM cascade, so the DB ondelete rules do the work
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

        assert await _count(session, User) == 0
        assert await _count(session, Course) == 0  # courses.user_id CASCADE
        assert await _count(session, ConversationMemory) == 0
        assert await _count(session, PracticeProblem) == 0  # via course CASCADE
        assert await _count(session, PracticeResult) == 0
        assert await _count(session, ChatSession) == 0
        assert await _count(session, UsageEvent) == 0  # usage_events.user_id CASCADE


@pytest.mark.asyncio
async def test_delete_course_sets_null_on_soft_references(session_factory):
    async with session_factory() as session:
        user, course, _problem = await _seed_user_graph(session)

        asset = GeneratedAsset(
            user_id=user.id,
            course_id=course.id,
            asset_type="notes",
            title="Generated notes",
            content={"blocks": []},
        )
        session.add(asset)
        await session.commit()

        await session.execute(delete(Course).where(Course.id == course.id))
        await session.commit()
        session.expire_all()

        # Soft references survive with course_id nulled out
        kept_asset = (await session.execute(select(GeneratedAsset))).scalar_one()
        assert kept_asset.course_id is None

        kept_memory = (await session.execute(select(ConversationMemory))).scalar_one()
        assert kept_memory.course_id is None

        kept_usage = (await session.execute(select(UsageEvent))).scalar_one()
        assert kept_usage.course_id is None

        # Hard children of the course are gone
        assert await _count(session, PracticeProblem) == 0
        assert await _count(session, ChatSession) == 0


@pytest.mark.asyncio
async def test_delete_content_node_cascades_subtree_and_nulls_problem_link(session_factory):
    async with session_factory() as session:
        user, course, _problem = await _seed_user_graph(session)

        root = CourseContentTree(course_id=course.id, title="Chapter 1", level=1)
        session.add(root)
        await session.flush()
        child = CourseContentTree(course_id=course.id, parent_id=root.id, title="Section 1.1", level=2)
        linked_problem = PracticeProblem(
            course_id=course.id, content_node_id=root.id, question_type="tf", question="True?"
        )
        session.add_all([child, linked_problem])
        await session.commit()
        linked_problem_id = linked_problem.id

        await session.execute(delete(CourseContentTree).where(CourseContentTree.id == root.id))
        await session.commit()
        session.expire_all()

        # Subtree cascades with the parent node
        assert await _count(session, CourseContentTree) == 0

        # Problem survives with its content_node link nulled
        kept = (
            await session.execute(select(PracticeProblem).where(PracticeProblem.id == linked_problem_id))
        ).scalar_one()
        assert kept.content_node_id is None


@pytest.mark.asyncio
async def test_delete_problem_cascades_results(session_factory):
    async with session_factory() as session:
        user, course, problem = await _seed_user_graph(session)
        assert await _count(session, PracticeResult) == 1

        await session.execute(delete(PracticeProblem).where(PracticeProblem.id == problem.id))
        await session.commit()

        assert await _count(session, PracticeResult) == 0
