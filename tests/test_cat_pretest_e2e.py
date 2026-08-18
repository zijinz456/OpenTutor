"""Integration tests — CAT diagnostic pretest with a realistic item bank (issue #40).

Validates ability-estimation convergence (standard error drops below the
threshold and the session stops), stopping-criteria configurability, and
finalization against a real in-memory SQLite database: tested concepts get
observed mastery, untested concepts get graph/theta-inferred mastery, and
real practice data is never overwritten.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery
from services.diagnosis.cat_pretest import (
    CATItem,
    CATState,
    finalize_pretest,
    load_testable_concepts,
    select_next_item,
    update_ability,
)

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


# ── Realistic item bank: 24 concepts across all Bloom levels ──

_BLOOM_LABELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]


async def _seed_item_bank(db: AsyncSession, course_id: uuid.UUID) -> list[KnowledgeNode]:
    """24-concept calculus item bank: 4 concepts per Bloom level 1–6."""
    nodes = []
    for bloom in range(1, 7):
        for i in range(4):
            node = KnowledgeNode(
                id=uuid.uuid4(),
                course_id=course_id,
                name=f"Concept B{bloom}-{i}",
                description=f"Bloom level {bloom} concept #{i}",
                metadata_={"bloom_level": bloom, "bloom_label": _BLOOM_LABELS[bloom - 1]},
            )
            db.add(node)
            nodes.append(node)
    await db.flush()

    # Prerequisite chain across difficulty bands for inference checks:
    # each B(n)-0 requires B(n-1)-0
    by_name = {n.name: n for n in nodes}
    for bloom in range(2, 7):
        db.add(KnowledgeEdge(
            source_id=by_name[f"Concept B{bloom}-0"].id,
            target_id=by_name[f"Concept B{bloom - 1}-0"].id,
            relation_type="prerequisite",
            weight=1.0,
        ))
    await db.commit()
    return nodes


def _simulate_student(items: list[CATItem], true_theta: float, max_steps: int = 50) -> tuple[CATState, list[float]]:
    """Run a full CAT session for a deterministic student.

    The student answers correctly iff the item's difficulty does not exceed
    their true ability. Returns the final state and the SE trajectory.
    """
    state = CATState()
    se_trajectory = []
    for _ in range(max_steps):
        if state.should_stop:
            break
        item = select_next_item(state, items)
        if item is None:
            break
        update_ability(state, item, correct=item.difficulty <= true_theta)
        se_trajectory.append(state.standard_error)
    return state, se_trajectory


# ── Item bank loading ──


@pytest.mark.asyncio
async def test_load_item_bank_maps_bloom_to_difficulty(db, course_id):
    await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    assert len(items) == 24
    difficulties = {i.difficulty for i in items}
    # Bloom 1 → 0.1 floor, Bloom 6 → 0.9 ceiling, monotone in between
    assert min(difficulties) == pytest.approx(0.1)
    assert max(difficulties) == pytest.approx(0.9)
    by_bloom = {}
    for i in items:
        by_bloom.setdefault(i.bloom_level, set()).add(i.difficulty)
    assert all(len(v) == 1 for v in by_bloom.values())  # Same bloom → same difficulty


# ── Convergence: SE drops below threshold and the session stops ──


@pytest.mark.asyncio
async def test_ability_estimation_converges(db, course_id):
    await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    state, se_trajectory = _simulate_student(items, true_theta=0.7)

    # Session terminated by the stopping rule, not by item exhaustion
    assert state.should_stop
    assert state.total_count <= 20
    # SE converged: strictly below the 1.0 cold-start value and trending down
    assert state.standard_error < se_trajectory[0]
    assert se_trajectory[-1] == min(se_trajectory[2:] + [se_trajectory[-1]])
    # Ability estimate lands in the neighborhood of true ability
    assert 0.45 <= state.theta <= 0.95


@pytest.mark.asyncio
async def test_consistent_student_stops_early(db, course_id):
    """A student who answers everything consistently triggers the SE early-stop."""
    await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    # true_theta=0.95: answers every item correctly → p ≈ 0.99 → tiny SE fast
    state, _ = _simulate_student(items, true_theta=0.95)

    assert state.total_count < 20  # Stopped well before the hard cap
    assert state.standard_error < 0.15


@pytest.mark.asyncio
async def test_stopping_criteria_configurable(db, course_id, monkeypatch):
    from config import settings

    await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    monkeypatch.setattr(settings, "cat_max_items", 7)
    state, _ = _simulate_student(items, true_theta=0.5)
    assert state.total_count <= 7

    # Tighter SE bar forces longer sessions for a noisy (boundary) student
    monkeypatch.setattr(settings, "cat_max_items", 20)
    monkeypatch.setattr(settings, "cat_se_threshold", 0.01)
    state2, _ = _simulate_student(items, true_theta=0.5)
    assert state2.total_count == 20  # Can never hit SE 0.01 → runs to the cap


def test_min_items_floor_prevents_premature_stop():
    state = CATState()
    item = CATItem(concept_id=uuid.uuid4(), concept_name="X", difficulty=0.5)
    # Two consistent answers give a tiny binomial SE, but min-items floor holds
    update_ability(state, item, correct=True)
    item2 = CATItem(concept_id=uuid.uuid4(), concept_name="Y", difficulty=0.5)
    update_ability(state, item2, correct=True)
    assert state.total_count == 2
    assert not state.should_stop


# ── Adaptive selection ──


@pytest.mark.asyncio
async def test_selection_tracks_ability_estimate(db, course_id):
    await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    state = CATState()  # theta starts at 0.5
    first = select_next_item(state, items)
    assert abs(first.difficulty - 0.5) == min(abs(i.difficulty - 0.5) for i in items)

    # After a correct answer theta rises; the next pick must not repeat the item
    update_ability(state, first, correct=True)
    second = select_next_item(state, items)
    assert second.concept_id != first.concept_id
    assert abs(second.difficulty - state.theta) == min(
        abs(i.difficulty - state.theta) for i in items if i.concept_id not in state.tested_ids
    )


# ── Finalization ──


@pytest.mark.asyncio
async def test_finalize_writes_mastery_for_all_concepts(db, user_id, course_id):
    await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    state, _ = _simulate_student(items, true_theta=0.7)
    summary = await finalize_pretest(db, user_id, course_id, state, items)

    assert summary["status"] == "completed"
    assert summary["questions_asked"] == state.total_count
    assert summary["concepts_assessed"] == 24
    assert summary["mastery_written"] == 24

    rows = (await db.execute(
        select(ConceptMastery).where(ConceptMastery.user_id == user_id)
    )).scalars().all()
    assert len(rows) == 24
    assert all(0.0 <= r.mastery_score <= 1.0 for r in rows)

    # Tested-correct concepts must outscore untested concepts the ability
    # estimate says are out of reach (difficulty above theta)
    tested_correct = {
        uuid.UUID(r["concept_id"]) for r in state.responses if r["correct"]
    }
    item_difficulty = {i.concept_id: i.difficulty for i in items}
    mastery_by_id = {r.knowledge_node_id: r.mastery_score for r in rows}
    hard_untested = [
        nid for nid, diff in item_difficulty.items()
        if nid not in state.tested_ids and diff > state.theta
    ]
    if tested_correct and hard_untested:
        assert min(mastery_by_id[c] for c in tested_correct) > max(
            mastery_by_id[h] for h in hard_untested
        )


@pytest.mark.asyncio
async def test_finalize_never_overwrites_real_practice_data(db, user_id, course_id):
    nodes = await _seed_item_bank(db, course_id)
    items = await load_testable_concepts(db, course_id)

    # This user already practiced one concept for real
    practiced = nodes[0]
    db.add(ConceptMastery(
        user_id=user_id, knowledge_node_id=practiced.id,
        mastery_score=0.92, practice_count=7, correct_count=6, wrong_count=1,
    ))
    await db.commit()

    state, _ = _simulate_student(items, true_theta=0.5)
    await finalize_pretest(db, user_id, course_id, state, items)

    row = (await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id == practiced.id,
        )
    )).scalar_one()
    assert row.mastery_score == pytest.approx(0.92)
    assert row.practice_count == 7
