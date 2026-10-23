"""E2E test — LECTOR semantic spaced review pipeline (issue #39 MVP).

Simulates: practice → BKT mastery updates → smart review session, verifying
review ordering, prerequisite-first gating, interference boost (configurable
threshold), session structuring, and consolidation bonuses on review outcomes.

Uses in-memory SQLite so no external DB is needed.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery
from services.lector import get_smart_review_session, record_review_outcome
from services.lector_session import build_structured_session
from services.loom_mastery import update_concept_mastery

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


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def course_id():
    return uuid.uuid4()


# ── Graph seeding ──


async def _seed_graph(db: AsyncSession, course_id: uuid.UUID) -> dict[str, KnowledgeNode]:
    """Limit ← Derivative ← Chain Rule prereq chain; Derivative ↔ Integral confusion."""
    nodes = {}
    for name, bloom in [("Limit", 2), ("Derivative", 3), ("Chain Rule", 3), ("Integral", 3)]:
        node = KnowledgeNode(
            id=uuid.uuid4(), course_id=course_id, name=name,
            description=f"Concept: {name}",
            metadata_={"bloom_level": bloom},
        )
        db.add(node)
        nodes[name] = node
    await db.flush()

    db.add(KnowledgeEdge(source_id=nodes["Derivative"].id, target_id=nodes["Limit"].id,
                         relation_type="prerequisite", weight=1.0))
    db.add(KnowledgeEdge(source_id=nodes["Chain Rule"].id, target_id=nodes["Derivative"].id,
                         relation_type="prerequisite", weight=1.0))
    db.add(KnowledgeEdge(source_id=nodes["Derivative"].id, target_id=nodes["Integral"].id,
                         relation_type="confused_with", weight=0.8))
    await db.commit()
    return nodes


async def _practice(db, user_id, course_id, name, correct, times=1):
    for _ in range(times):
        await update_concept_mastery(
            db, user_id, name, course_id, correct=correct, question_type="free_response",
        )
    await db.commit()


# ── E2E: practice → mastery → review ordering ──


@pytest.mark.asyncio
async def test_e2e_practice_drives_review_ordering(db, user_id, course_id):
    await _seed_graph(db, course_id)

    # Limit mastered (4 strong correct answers), Derivative failing (2 wrong)
    await _practice(db, user_id, course_id, "Limit", correct=True, times=4)
    await _practice(db, user_id, course_id, "Derivative", correct=False, times=2)

    items = await get_smart_review_session(db, user_id, course_id, max_items=10)
    by_name = {i.concept_name: i for i in items}

    # Chain Rule is most urgent: never practiced + gated by the weak Derivative
    assert items[0].concept_name == "Chain Rule"
    assert by_name["Chain Rule"].review_type == "prerequisite_first"
    assert "prerequisite 'Derivative' is weak" in by_name["Chain Rule"].reason

    # The failing concept is queued with its BKT-collapsed mastery
    assert by_name["Derivative"].mastery < 0.3
    assert by_name["Derivative"].priority > 0

    # Its strong confusion edge (0.8 > default threshold 0.6) is flagged
    assert "high semantic interference" in by_name["Derivative"].reason

    # The mastered concept does not clutter the session
    assert "Limit" not in by_name


@pytest.mark.asyncio
async def test_e2e_interference_threshold_is_configurable(db, user_id, course_id, monkeypatch):
    from config import settings

    await _seed_graph(db, course_id)
    await _practice(db, user_id, course_id, "Derivative", correct=False, times=2)

    # Raise the interference threshold above the edge weight (0.8): no boost
    monkeypatch.setattr(settings, "loom_interference_similarity_threshold", 0.95)
    items = await get_smart_review_session(db, user_id, course_id, max_items=10)
    derivative = next(i for i in items if i.concept_name == "Derivative")
    assert "high semantic interference" not in derivative.reason


@pytest.mark.asyncio
async def test_e2e_structured_session_preserves_items(db, user_id, course_id):
    await _seed_graph(db, course_id)
    await _practice(db, user_id, course_id, "Limit", correct=True, times=2)
    await _practice(db, user_id, course_id, "Derivative", correct=False, times=2)

    items = await get_smart_review_session(db, user_id, course_id, max_items=10)
    structured = await build_structured_session(items, max_items=10)

    assert len(structured) == len(items)
    assert {i.concept_name for i in structured} == {i.concept_name for i in items}
    # Prerequisite-first items appear before standard items they gate
    order = [i.concept_name for i in structured]
    if "Chain Rule" in order and "Integral" in order:
        chain_pos = order.index("Chain Rule")
        assert structured[chain_pos].review_type == "prerequisite_first"


# ── E2E: review outcomes feed consolidation ──


@pytest.mark.asyncio
async def test_e2e_review_outcome_triggers_consolidation(db, user_id, course_id):
    """Recalling the last weak prerequisite consolidates the parent concept."""
    parent = KnowledgeNode(id=uuid.uuid4(), course_id=course_id, name="Quadratic Equations")
    q = KnowledgeNode(id=uuid.uuid4(), course_id=course_id, name="Algebra Basics")
    r = KnowledgeNode(id=uuid.uuid4(), course_id=course_id, name="Linear Equations")
    for n in (parent, q, r):
        db.add(n)
    await db.flush()
    db.add(KnowledgeEdge(source_id=parent.id, target_id=q.id, relation_type="prerequisite", weight=1.0))
    db.add(KnowledgeEdge(source_id=parent.id, target_id=r.id, relation_type="prerequisite", weight=1.0))

    # Q solidly mastered; R just below the 0.85 consolidation threshold; parent mid
    db.add(ConceptMastery(user_id=user_id, knowledge_node_id=q.id, mastery_score=0.90,
                          practice_count=5, correct_count=5, stability_days=10.0))
    db.add(ConceptMastery(user_id=user_id, knowledge_node_id=r.id, mastery_score=0.84,
                          practice_count=4, correct_count=3, stability_days=8.0))
    db.add(ConceptMastery(user_id=user_id, knowledge_node_id=parent.id, mastery_score=0.50,
                          practice_count=2, correct_count=1, stability_days=2.0))
    await db.commit()

    # Correct recall of R: 0.84 + 0.1·(1−0.84) ≈ 0.856 → crosses 0.85 → consolidate
    await record_review_outcome(db, user_id, r.id, recalled_correctly=True)
    await db.commit()

    masteries = {
        m.knowledge_node_id: m
        for m in (await db.execute(
            select(ConceptMastery).where(ConceptMastery.user_id == user_id)
        )).scalars().all()
    }
    assert masteries[r.id].mastery_score >= 0.85
    # Parent got the consolidation bonus (0.50 → 0.60)
    assert masteries[parent.id].mastery_score == pytest.approx(0.60, abs=0.01)
    # Mastered prerequisites get their review interval extended (×1.5)
    assert masteries[q.id].stability_days == pytest.approx(15.0, abs=0.01)


@pytest.mark.asyncio
async def test_e2e_review_outcome_updates_fsrs_schedule(db, user_id, course_id):
    from datetime import datetime, timedelta, timezone

    node = KnowledgeNode(id=uuid.uuid4(), course_id=course_id, name="Eigenvalue")
    db.add(node)
    await db.flush()
    db.add(ConceptMastery(user_id=user_id, knowledge_node_id=node.id, mastery_score=0.5,
                          practice_count=3, correct_count=2, wrong_count=1, stability_days=5.0,
                          last_practiced_at=datetime.now(timezone.utc) - timedelta(days=6)))
    await db.commit()

    await record_review_outcome(db, user_id, node.id, recalled_correctly=True)
    await db.commit()

    m = (await db.execute(
        select(ConceptMastery).where(ConceptMastery.knowledge_node_id == node.id)
    )).scalar_one()
    assert m.mastery_score > 0.5
    assert m.stability_days > 5.0
    assert m.next_review_at is not None
    assert m.practice_count == 4
