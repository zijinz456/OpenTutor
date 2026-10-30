"""Tests for coarse knowledge points and problem/card → concept linking."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.course import Course
from models.generated_asset import GeneratedAsset
from models.knowledge_graph import KnowledgeNode
from models.practice import PracticeProblem
from models.user import User
from services.loom_linking import ConceptResolver, link_course_assets_to_concepts, normalize_concept_name
from services.practice.annotation import build_practice_problem


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _question(core_concept="Chain Rule"):
    return {
        "question_type": "mc",
        "question": "Which rule differentiates a composition of functions?",
        "options": {"A": "Chain", "B": "Product", "C": "Quotient", "D": "Power"},
        "correct_answer": "A",
        "explanation": "The chain rule handles compositions.",
        "difficulty_layer": 2,
        "problem_metadata": {"core_concept": core_concept, "bloom_level": "apply"},
    }


def test_knowledge_points_default_to_core_concept():
    problem = build_practice_problem(
        course_id=uuid.uuid4(), content_node_id=None, title="Derivatives",
        question=_question("Chain Rule"), source="extracted",
    )
    assert problem.knowledge_points == ["Chain Rule"]
    assert problem.problem_metadata["core_concept"] == "Chain Rule"


def test_explicit_knowledge_points_are_kept():
    problem = build_practice_problem(
        course_id=uuid.uuid4(), content_node_id=None, title="Derivatives",
        question=_question("Chain Rule"), knowledge_points=["Composition"],
    )
    assert problem.knowledge_points == ["Composition"]


def test_normalize_concept_name():
    assert normalize_concept_name("  The Chain-Rule! ") == "the chain rule"


@pytest.mark.asyncio
async def test_resolver_name_match_then_embedding():
    cid = uuid.uuid4()
    chain = KnowledgeNode(id=uuid.uuid4(), course_id=cid, name="Chain Rule", description="composition")
    limit = KnowledgeNode(id=uuid.uuid4(), course_id=cid, name="Limit", description="approach")
    resolver = ConceptResolver([chain, limit])

    assert await resolver.resolve("chain rule") == chain.id

    vectors = {
        "Chain Rule: composition": [1.0, 0.0],
        "Limit: approach": [0.0, 1.0],
        "limits of sequences": [0.1, 0.99],
        "unrelated": [0.7, 0.7],
    }

    async def _embed(text):
        return vectors.get(text)

    with patch("services.memory.pipeline.generate_embedding", AsyncMock(side_effect=_embed)):
        assert await resolver.resolve("limits of sequences") == limit.id
        assert await resolver.resolve("unrelated") is None


@pytest.mark.asyncio
async def test_link_course_assets_stores_node_ids(db):
    user = User(id=uuid.uuid4(), name="u")
    db.add(user)
    await db.flush()
    course = Course(id=uuid.uuid4(), user_id=user.id, name="Calc")
    db.add(course)
    await db.flush()
    node = KnowledgeNode(id=uuid.uuid4(), course_id=course.id, name="Chain Rule", description="")
    db.add(node)
    problem = build_practice_problem(
        course_id=course.id, content_node_id=None, title="Derivatives", question=_question("chain rule"),
    )
    db.add(problem)
    asset = GeneratedAsset(
        user_id=user.id, course_id=course.id, asset_type="flashcards", title="cards",
        content={"cards": [{"front": "q", "back": "a", "concept": "Chain Rule"}, {"front": "q2", "back": "a2", "concept": "Nope"}]},
    )
    db.add(asset)
    await db.commit()

    with patch("services.memory.pipeline.generate_embedding", AsyncMock(return_value=None)):
        counts = await link_course_assets_to_concepts(db, course.id)
    await db.commit()

    assert counts == {"problems": 1, "cards": 1}
    stored = (await db.execute(select(PracticeProblem))).scalar_one()
    assert stored.problem_metadata["knowledge_node_id"] == str(node.id)
    cards = (await db.execute(select(GeneratedAsset))).scalar_one().content["cards"]
    assert cards[0]["knowledge_node_id"] == str(node.id)
    assert "knowledge_node_id" not in cards[1]

    # Re-running is idempotent
    with patch("services.memory.pipeline.generate_embedding", AsyncMock(return_value=None)):
        assert await link_course_assets_to_concepts(db, course.id) == {"problems": 0, "cards": 0}
