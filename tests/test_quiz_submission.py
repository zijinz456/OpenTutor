"""Unit tests for the quiz answer submission flow (issue #32).

Calls the ``submit_answer`` endpoint function directly against a real
in-memory SQLite database (auth dependency bypassed by passing the user),
with the LLM-backed error classifier mocked for determinism.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from libs.exceptions import NotFoundError
from models.course import Course
from models.ingestion import WrongAnswer
from models.knowledge_graph import ConceptMastery, KnowledgeNode
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from routers.quiz_submission import submit_answer
from schemas.quiz import SubmitAnswerRequest

# ── Fixtures ──


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def user(db):
    u = User(id=uuid.uuid4(), name="Quiz Tester")
    db.add(u)
    await db.flush()
    return u


@pytest_asyncio.fixture
async def course(db, user):
    c = Course(id=uuid.uuid4(), user_id=user.id, name="Geography 101")
    db.add(c)
    await db.flush()
    return c


async def _make_problem(db, course, *, correct_answer="Paris", knowledge_points=None,
                        question_type="short_answer"):
    p = PracticeProblem(
        id=uuid.uuid4(),
        course_id=course.id,
        question_type=question_type,
        question="Capital of France?",
        correct_answer=correct_answer,
        explanation="Paris has been the capital since 987.",
        knowledge_points=knowledge_points or [],
    )
    db.add(p)
    await db.commit()
    return p


async def _submit(db, user, problem_id, answer, tasks=None):
    return await submit_answer(
        body=SubmitAnswerRequest(problem_id=problem_id, user_answer=answer),
        background_tasks=tasks or BackgroundTasks(),
        user=user,
        db=db,
    )


# ── Happy path ──


@pytest.mark.asyncio
async def test_correct_answer_returns_proper_grade(db, user, course):
    problem = await _make_problem(db, course)
    resp = await _submit(db, user, problem.id, "Paris")

    assert resp.is_correct is True
    assert resp.correct_answer == "Paris"
    assert resp.explanation == "Paris has been the capital since 987."
    assert resp.warnings == []

    results = (await db.execute(select(PracticeResult))).scalars().all()
    assert len(results) == 1 and results[0].is_correct is True
    # Correct answers never create wrong-answer records
    assert (await db.execute(select(WrongAnswer))).scalars().all() == []


@pytest.mark.asyncio
async def test_grading_is_case_and_whitespace_insensitive(db, user, course):
    problem = await _make_problem(db, course, correct_answer="paris")
    resp = await _submit(db, user, problem.id, "  PARIS ")
    assert resp.is_correct is True


# ── Wrong answers ──


@pytest.mark.asyncio
async def test_incorrect_answer_triggers_error_classification(db, user, course):
    problem = await _make_problem(db, course)
    classify = AsyncMock(return_value={"category": "conceptual", "detail": "confused with Lyon"})
    with patch("services.diagnosis.classifier.classify_error", classify):
        resp = await _submit(db, user, problem.id, "Lyon")

    assert resp.is_correct is False
    classify.assert_awaited_once()

    result = (await db.execute(select(PracticeResult))).scalar_one()
    assert result.error_category == "conceptual"

    wa = (await db.execute(select(WrongAnswer))).scalar_one()
    assert wa.user_answer == "Lyon" and wa.error_category == "conceptual"


@pytest.mark.asyncio
async def test_classifier_failure_degrades_with_warning(db, user, course):
    problem = await _make_problem(db, course)
    with patch(
        "services.diagnosis.classifier.classify_error",
        AsyncMock(side_effect=ValueError("LLM unavailable")),
    ):
        resp = await _submit(db, user, problem.id, "Lyon")

    assert resp.is_correct is False
    assert "error_classification_failed" in resp.warnings
    # The submission itself must still persist
    assert (await db.execute(select(PracticeResult))).scalar_one().is_correct is False


@pytest.mark.asyncio
async def test_wrong_answer_schedules_background_diagnostics(db, user, course):
    problem = await _make_problem(db, course)
    tasks = BackgroundTasks()
    with patch(
        "services.diagnosis.classifier.classify_error",
        AsyncMock(return_value={"category": "careless"}),
    ):
        await _submit(db, user, problem.id, "Lyon", tasks=tasks)
    # auto-derive diagnostic + confusion detection
    assert len(tasks.tasks) == 2


@pytest.mark.asyncio
async def test_correct_answer_schedules_effective_review_check(db, user, course):
    problem = await _make_problem(db, course)
    tasks = BackgroundTasks()
    await _submit(db, user, problem.id, "Paris", tasks=tasks)
    assert len(tasks.tasks) == 1


# ── Error cases ──


@pytest.mark.asyncio
async def test_unknown_problem_id_raises_not_found(db, user, course):
    with pytest.raises(NotFoundError):
        await _submit(db, user, uuid.uuid4(), "Paris")


@pytest.mark.asyncio
async def test_other_users_problem_is_not_found(db, user, course):
    # A problem in someone else's course must be invisible to this user
    other = User(id=uuid.uuid4(), name="Other")
    db.add(other)
    await db.flush()
    other_course = Course(id=uuid.uuid4(), user_id=other.id, name="Private")
    db.add(other_course)
    await db.flush()
    problem = await _make_problem(db, other_course)

    with pytest.raises(NotFoundError):
        await _submit(db, user, problem.id, "Paris")


# ── Mastery updates ──


@pytest.mark.asyncio
async def test_mastery_updated_for_knowledge_points(db, user, course):
    node = KnowledgeNode(id=uuid.uuid4(), course_id=course.id, name="French Geography")
    db.add(node)
    await db.flush()
    problem = await _make_problem(db, course, knowledge_points=["French Geography"])

    resp = await _submit(db, user, problem.id, "Paris")

    assert resp.is_correct is True
    mastery = (await db.execute(
        select(ConceptMastery).where(ConceptMastery.knowledge_node_id == node.id)
    )).scalar_one()
    assert mastery.practice_count == 1
    assert mastery.correct_count == 1
    assert mastery.mastery_score > 0.0
