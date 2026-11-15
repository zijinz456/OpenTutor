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
from libs.exceptions import NotFoundError, ValidationError
from models.course import Course
from models.ingestion import WrongAnswer
from models.knowledge_graph import ConceptMastery, KnowledgeNode
from models.practice import PracticeProblem, PracticeResult
from models.progress import LearningProgress
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
@pytest.mark.parametrize("reference", ["Paris", None])
async def test_other_users_problem_is_not_found(db, user, course, reference):
    # A problem in someone else's course must be invisible to this user
    other = User(id=uuid.uuid4(), name="Other")
    db.add(other)
    await db.flush()
    other_course = Course(id=uuid.uuid4(), user_id=other.id, name="Private")
    db.add(other_course)
    await db.flush()
    problem = await _make_problem(db, other_course, correct_answer=reference)

    with pytest.raises(NotFoundError):
        await _submit(db, user, problem.id, "Paris")


@pytest.mark.asyncio
@pytest.mark.parametrize("question_type", ["short_answer", "fill_blank", "mc", "tf", "select_all"])
@pytest.mark.parametrize("reference", [None, "", " \t\n "])
async def test_missing_reference_is_not_a_wrong_answer(db, user, course, question_type, reference):
    node = KnowledgeNode(id=uuid.uuid4(), course_id=course.id, name="French Geography")
    db.add(node)
    problem = await _make_problem(
        db, course, correct_answer=reference, question_type=question_type,
        knowledge_points=[node.name],
    )
    tasks = BackgroundTasks()
    with (
        patch("services.diagnosis.classifier.classify_error", AsyncMock(return_value={"category": "careless"})) as classify,
        patch("services.analytics.events.emit_quiz_answered", AsyncMock()) as emit,
    ):
        with pytest.raises(ValidationError, match="reference answer") as exc:
            await _submit(db, user, problem.id, "Paris", tasks=tasks)
    assert exc.value.status == 422
    classify.assert_not_awaited()
    emit.assert_not_awaited()
    assert tasks.tasks == []
    for model in (PracticeResult, WrongAnswer, LearningProgress, ConceptMastery):
        assert (await db.execute(select(model))).scalars().all() == []


@pytest.mark.asyncio
async def test_coding_without_reference_still_uses_its_grader(db, user, course):
    problem = await _make_problem(db, course, correct_answer=None, question_type="coding")
    with patch(
        "services.diagnosis.coding_grader.grade_coding_answer",
        AsyncMock(return_value={"is_correct": True}),
    ) as grade:
        response = await _submit(db, user, problem.id, "print('Paris')")
    assert response.is_correct is True
    grade.assert_awaited_once()
    assert grade.await_args.kwargs["reference_answer"] == ""
    assert (await db.execute(select(PracticeResult))).scalar_one().is_correct is True


@pytest.mark.asyncio
async def test_missing_reference_returns_http_error_without_grading(db, user, course):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from database import get_db
    from libs.exceptions import AppError
    from main import app_error_handler
    from routers.quiz_submission import router
    from services.auth.dependency import get_current_user

    problem = await _make_problem(db, course, correct_answer=None)
    app = FastAPI()
    app.include_router(router, prefix="/quiz")
    app.add_exception_handler(AppError, app_error_handler)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/quiz/submit", json={
            "problem_id": str(problem.id), "user_answer": "Paris",
        })
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "reference answer" in response.json()["message"]
    assert "is_correct" not in response.json()
    assert (await db.execute(select(PracticeResult))).scalars().all() == []


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


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,expected", [
    ("b,a", True), (" B ; a ", True), ("A/B", True), ("B|A", True),
    ("A", False), ("A,C", False), ("A,B,C", False), ("A,B,Z", False),
    ("A,A,B", False), ("", False), ("A,,B", False), ("AB", False),
])
async def test_select_all_grades_complete_sets_and_persists_result(db, user, course, answer, expected):
    problem = await _make_problem(db, course, correct_answer="A,B", question_type="select_all")
    problem.options = {"A": "Red", "B": "Blue", "C": "Green", "D": "Orange"}
    await db.commit()
    with patch("services.diagnosis.classifier.classify_error", AsyncMock(return_value={"category": "careless"})):
        response = await _submit(db, user, problem.id, answer)
    assert response.is_correct is expected
    result = (await db.execute(select(PracticeResult))).scalar_one()
    assert result.is_correct is expected
    assert result.user_answer == answer
    wrong = (await db.execute(select(WrongAnswer))).scalars().all()
    assert len(wrong) == (0 if expected else 1)


@pytest.mark.parametrize("reference,options", [
    ("", {"A": "one", "B": "two"}),
    ("A,A,B", {"A": "one", "B": "two"}),
    ("A,Z", {"A": "one", "B": "two"}),
    ("A,B", None),
])
def test_select_all_invalid_reference_cannot_grade_correct(reference, options):
    from services.practice.answers import grade_select_all_answer
    assert grade_select_all_answer(reference, reference, options) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("question_type", ["short_answer", "fill_blank"])
@pytest.mark.parametrize("answer", ["2.0", " 2e0 ", "+02.000"])
async def test_explicit_numeric_question_survives_import_and_grades_equivalent_value(db, user, course, question_type, answer):
    from services.practice.annotation import build_practice_problem
    problem = build_practice_problem(
        course_id=course.id, content_node_id=None, title="Arithmetic",
        question={"question_type": question_type, "question": "Calculate one plus one.",
                  "correct_answer": "2", "explanation": "One plus one equals two.",
                  "problem_metadata": {"answer_type": "number"}},
    )
    db.add(problem)
    await db.commit()
    with patch("services.diagnosis.classifier.classify_error", AsyncMock(return_value={"category": "careless"})):
        response = await _submit(db, user, problem.id, answer)
    assert response.is_correct is True
    assert problem.problem_metadata["answer_type"] == "number"
    result = (await db.execute(select(PracticeResult))).scalar_one()
    assert result.is_correct is True and result.user_answer == answer
    assert (await db.execute(select(WrongAnswer))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("question_type,metadata,reference,answer", [
    ("short_answer", None, "2", "2.0"),
    ("fill_blank", {"answer_type": "text"}, "0012", "12"),
    ("short_answer", {}, "2.0", "2"),
    ("short_answer", {"answer_type": "numeric"}, "2", "2.0"),
    ("mc", {"answer_type": "number"}, "2", "2.0"),
    ("free_response", {"answer_type": "number"}, "2", "2.0"),
    ("short_answer", {"answer_type": "number"}, "NaN", "NaN"),
    ("fill_blank", {"answer_type": "number"}, "Infinity", "Infinity"),
])
async def test_numeric_grading_never_guesses_text_semantics_or_accepts_nonfinite_values(db, user, course, question_type, metadata, reference, answer):
    problem = await _make_problem(db, course, correct_answer=reference, question_type=question_type)
    problem.problem_metadata = metadata
    await db.commit()
    with patch("services.diagnosis.classifier.classify_error", AsyncMock(return_value={"category": "careless"})):
        response = await _submit(db, user, problem.id, answer)
    assert response.is_correct is False
    assert (await db.execute(select(PracticeResult))).scalar_one().is_correct is False
