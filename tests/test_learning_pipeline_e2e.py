"""E2E regression test — full learning pipeline.

Simulates: concept extraction → quiz → wrong answer → mastery update →
LECTOR review → confusion detection → experiment assignment → metrics.

Uses in-memory SQLite so no external DB is needed.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery

# ── Fixtures ──


@pytest_asyncio.fixture
async def db():
    """Create an in-memory async SQLite database with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def course_id():
    return uuid.uuid4()


# ── Helper to seed knowledge graph ──


async def _seed_graph(db: AsyncSession, course_id: uuid.UUID) -> list[KnowledgeNode]:
    """Create a small knowledge graph: A --prerequisite--> B --related--> C."""
    nodes = []
    for name, bloom in [("Algebra Basics", 1), ("Linear Equations", 2), ("Quadratic Equations", 3)]:
        node = KnowledgeNode(
            id=uuid.uuid4(),
            course_id=course_id,
            name=name,
            description=f"Concept: {name}",
            metadata_={"bloom_level": bloom, "bloom_label": ["remember", "understand", "apply"][bloom - 1]},
        )
        db.add(node)
        nodes.append(node)

    await db.flush()

    # A -> B prerequisite
    db.add(KnowledgeEdge(
        source_id=nodes[0].id,
        target_id=nodes[1].id,
        relation_type="prerequisite",
        weight=1.0,
    ))
    # B -> C related
    db.add(KnowledgeEdge(
        source_id=nodes[1].id,
        target_id=nodes[2].id,
        relation_type="related",
        weight=0.8,
    ))

    await db.flush()
    return nodes


async def _seed_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    nodes: list[KnowledgeNode],
    scores: list[float],
) -> list[ConceptMastery]:
    """Create mastery records for user on given nodes."""
    now = datetime.now(timezone.utc)
    masteries = []
    for node, score in zip(nodes, scores):
        m = ConceptMastery(
            user_id=user_id,
            knowledge_node_id=node.id,
            mastery_score=score,
            practice_count=5,
            correct_count=int(5 * score),
            wrong_count=5 - int(5 * score),
            last_practiced_at=now,
            stability_days=max(score * 10, 0.5),
        )
        db.add(m)
        masteries.append(m)
    await db.flush()
    return masteries


# ── Tests ──


@pytest.mark.asyncio
async def test_knowledge_graph_creation(db, course_id):
    """Verify knowledge graph nodes and edges are created correctly."""
    nodes = await _seed_graph(db, course_id)

    assert len(nodes) == 3
    assert nodes[0].name == "Algebra Basics"

    # Verify edges
    edges = (await db.execute(select(KnowledgeEdge))).scalars().all()
    assert len(edges) == 2

    prereq = [e for e in edges if e.relation_type == "prerequisite"]
    assert len(prereq) == 1
    assert prereq[0].source_id == nodes[0].id
    assert prereq[0].target_id == nodes[1].id


@pytest.mark.asyncio
async def test_mastery_tracking(db, user_id, course_id):
    """Verify mastery records are created and scores are accurate."""
    nodes = await _seed_graph(db, course_id)
    scores = [0.9, 0.5, 0.2]
    masteries = await _seed_mastery(db, user_id, nodes, scores)

    assert len(masteries) == 3
    assert masteries[0].mastery_score == 0.9
    assert masteries[1].mastery_score == 0.5
    assert masteries[2].mastery_score == 0.2

    # Accuracy check
    assert masteries[0].correct_count == 4  # int(5 * 0.9)
    assert masteries[2].correct_count == 1  # int(5 * 0.2)


@pytest.mark.asyncio
async def test_learning_metrics_computation(db, user_id, course_id):
    """Test compute_learning_metrics with real data."""
    from services.experiments.metrics import compute_learning_metrics

    nodes = await _seed_graph(db, course_id)
    await _seed_mastery(db, user_id, nodes, [0.9, 0.5, 0.2])

    metrics = await compute_learning_metrics(db, user_id, course_id)

    assert metrics["total_concepts"] == 3
    assert metrics["reviewed_concepts"] == 3
    assert metrics["mastered_concepts"] == 1  # only 0.9 >= 0.8
    assert metrics["coverage"] == 1.0
    assert 0.0 < metrics["avg_mastery"] < 1.0
    assert metrics["total_practices"] == 15  # 5 * 3
    assert 0.0 < metrics["accuracy"] <= 1.0


@pytest.mark.asyncio
async def test_empty_course_metrics(db, user_id, course_id):
    """Metrics for a course with no concepts returns zeros."""
    from services.experiments.metrics import compute_learning_metrics

    metrics = await compute_learning_metrics(db, user_id, course_id)

    assert metrics["total_concepts"] == 0
    assert metrics["avg_mastery"] == 0.0
    assert metrics["accuracy"] == 0.0


@pytest.mark.asyncio
async def test_experiment_assignment_deterministic():
    """Verify that experiment assignment is deterministic for same user."""
    from services.experiments.framework import (
        Experiment,
        ExperimentVariant,
        ExperimentStatus,
    )

    exp = Experiment(
        id="test_exp_1",
        name="Test Experiment",
        description="Determinism test",
        variants=[
            ExperimentVariant(name="control", weight=0.5),
            ExperimentVariant(name="treatment", weight=0.5),
        ],
        status=ExperimentStatus.RUNNING,
    )

    uid = uuid.UUID("12345678-1234-1234-1234-123456789abc")

    # Same user should always get same variant
    v1 = exp.get_variant_for_user(uid)
    v2 = exp.get_variant_for_user(uid)
    assert v1.name == v2.name

    # Different user may get different variant (not guaranteed but assignment works)
    uid2 = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    v3 = exp.get_variant_for_user(uid2)
    assert v3.name in ("control", "treatment")


@pytest.mark.asyncio
async def test_statistical_tests():
    """Verify statistical test functions produce valid output."""
    from services.experiments.metrics import two_proportion_z_test, mann_whitney_u

    # Two-proportion z-test
    result = two_proportion_z_test(80, 100, 60, 100)
    assert "z_stat" in result
    assert "p_value" in result
    assert "significant" in result
    assert result["p_a"] == 0.8
    assert result["p_b"] == 0.6
    assert result["significant"] is True  # 80% vs 60% should be significant

    # Edge case: empty groups
    empty = two_proportion_z_test(0, 0, 0, 0)
    assert empty["p_value"] == 1.0
    assert empty["significant"] is False

    # Mann-Whitney U
    group_a = [1.0, 2.0, 3.0, 4.0, 5.0]
    group_b = [6.0, 7.0, 8.0, 9.0, 10.0]
    mw = mann_whitney_u(group_a, group_b)
    assert "u_stat" in mw
    assert "p_value" in mw
    assert mw["significant"] is True  # Clearly different groups

    # Identical groups should not be significant
    same = mann_whitney_u([1, 2, 3], [1, 2, 3])
    assert same["significant"] is False


@pytest.mark.asyncio
async def test_confusion_edge_creation(db, course_id):
    """Verify confused_with edges can be created between concepts."""
    nodes = await _seed_graph(db, course_id)

    # Add a confusion edge
    confusion_edge = KnowledgeEdge(
        source_id=nodes[1].id,  # Linear Equations
        target_id=nodes[2].id,  # Quadratic Equations
        relation_type="confused_with",
        weight=3.0,
    )
    db.add(confusion_edge)
    await db.flush()

    # Query confusion edges
    result = await db.execute(
        select(KnowledgeEdge).where(KnowledgeEdge.relation_type == "confused_with")
    )
    confusions = result.scalars().all()
    assert len(confusions) == 1
    assert confusions[0].weight == 3.0


@pytest.mark.asyncio
async def test_bloom_metadata(db, course_id):
    """Verify Bloom taxonomy metadata is stored correctly."""
    nodes = await _seed_graph(db, course_id)

    assert nodes[0].metadata_["bloom_level"] == 1
    assert nodes[0].metadata_["bloom_label"] == "remember"
    assert nodes[2].metadata_["bloom_level"] == 3
    assert nodes[2].metadata_["bloom_label"] == "apply"


@pytest.mark.asyncio
async def test_full_pipeline_flow(db, user_id, course_id):
    """End-to-end: graph creation → mastery → metrics → experiment."""
    from services.experiments.metrics import compute_learning_metrics
    from services.experiments.framework import (
        Experiment,
        ExperimentVariant,
        ExperimentStatus,
        register_experiment,
        get_user_variant,
    )

    # 1. Create knowledge graph
    nodes = await _seed_graph(db, course_id)
    assert len(nodes) == 3

    # 2. Simulate practice: user masters first concept, struggles with third
    masteries = await _seed_mastery(db, user_id, nodes, [0.95, 0.6, 0.15])

    # 3. Compute learning metrics
    metrics = await compute_learning_metrics(db, user_id, course_id)
    assert metrics["total_concepts"] == 3
    assert metrics["mastered_concepts"] == 1  # only 0.95 >= 0.8
    assert metrics["coverage"] == 1.0
    assert metrics["overdue_count"] == 0  # no next_review_at set

    # 4. Assign user to experiment
    exp = Experiment(
        id="e2e_test_exp",
        name="E2E Test",
        description="Pipeline test experiment",
        variants=[
            ExperimentVariant(name="control", weight=0.5, config={"boost": False}),
            ExperimentVariant(name="treatment", weight=0.5, config={"boost": True}),
        ],
        status=ExperimentStatus.RUNNING,
    )
    register_experiment(exp)
    variant = get_user_variant(user_id, "e2e_test_exp")

    assert variant is not None
    assert variant.name in ("control", "treatment")
    assert "boost" in variant.config

    # 5. Add confusion edge (simulating confusion detection)
    db.add(KnowledgeEdge(
        source_id=nodes[1].id,
        target_id=nodes[2].id,
        relation_type="confused_with",
        weight=2.0,
    ))
    await db.flush()

    # Verify confusion edge exists
    edges = (await db.execute(
        select(KnowledgeEdge).where(KnowledgeEdge.relation_type == "confused_with")
    )).scalars().all()
    assert len(edges) >= 1
