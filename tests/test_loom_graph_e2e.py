"""E2E test — LOOM knowledge graph auto-build pipeline (issue #38 MVP).

Simulates: content upload → build_course_graph → verify persisted
nodes/edges, idempotent rebuild, Graphusion fusion dedup (including the
LOOM_FUSION_SIMILARITY_THRESHOLD override), and cross-course linking.

Uses in-memory SQLite so no external DB is needed.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.content import CourseContentTree
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge
from services.loom_extraction import _fuse_concepts, _fusion_threshold
from services.loom_graph import build_course_graph, link_cross_course_concepts

# ── Fixtures ──


@pytest_asyncio.fixture
async def session_factory():
    """In-memory async SQLite database with all tables; yields the sessionmaker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory

    await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def course_id():
    return uuid.uuid4()


# ── Helpers ──

_CONCEPTS_JSON = (
    '[{"name":"Limit","description":"Value a function approaches","prerequisites":[],'
    '"related":[],"bloom_level":"understand"},'
    '{"name":"Derivative","description":"Rate of change of a function","prerequisites":["Limit"],'
    '"related":["Limit"],"bloom_level":"apply"},'
    '{"name":"Chain Rule","description":"Derivative of composed functions","prerequisites":["Derivative"],'
    '"related":[],"bloom_level":"apply"}]'
)


async def _seed_content(db: AsyncSession, course_id: uuid.UUID, sections: int = 2) -> None:
    """Simulate an uploaded document parsed into content tree nodes."""
    for i in range(sections):
        db.add(CourseContentTree(
            id=uuid.uuid4(),
            course_id=course_id,
            title=f"Chapter {i + 1}",
            content=f"Section {i + 1} on calculus. " + "Limits and derivatives explained. " * 10,
            level=1,
            order_index=i,
        ))
    await db.commit()


def _llm_client(response: str = _CONCEPTS_JSON):
    client = AsyncMock()
    client.extract = AsyncMock(return_value=(response, {}))
    return client


def _build_patches(client):
    """Patch the LLM client and neutralize embedding/confusion side paths."""
    return (
        patch("services.llm.router.get_llm_client", return_value=client),
        patch("services.memory.pipeline.generate_embedding", AsyncMock(return_value=None)),
        patch("services.loom_confusion.compute_interference_matrix", AsyncMock(return_value=0)),
    )


# ── E2E: upload → build → verify ──


@pytest.mark.asyncio
async def test_e2e_build_graph_from_content(session_factory, course_id):
    async with session_factory() as db:
        await _seed_content(db, course_id)

    p1, p2, p3 = _build_patches(_llm_client())
    with p1, p2, p3:
        count = await build_course_graph(session_factory, course_id)

    assert count == 3

    async with session_factory() as db:
        nodes = (await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
        )).scalars().all()
        assert {n.name for n in nodes} == {"Limit", "Derivative", "Chain Rule"}

        by_name = {n.name: n for n in nodes}
        assert by_name["Derivative"].metadata_["bloom_level"] == 3  # "apply"
        assert by_name["Limit"].description == "Value a function approaches"

        edges = (await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id.in_([n.id for n in nodes])
            )
        )).scalars().all()
        prereqs = {(e.source_id, e.target_id) for e in edges if e.relation_type == "prerequisite"}
        related = {(e.source_id, e.target_id) for e in edges if e.relation_type == "related"}

        # Derivative requires Limit; Chain Rule requires Derivative
        assert (by_name["Derivative"].id, by_name["Limit"].id) in prereqs
        assert (by_name["Chain Rule"].id, by_name["Derivative"].id) in prereqs
        assert (by_name["Derivative"].id, by_name["Limit"].id) in related


@pytest.mark.asyncio
async def test_e2e_rebuild_is_idempotent(session_factory, course_id):
    async with session_factory() as db:
        await _seed_content(db, course_id)

    p1, p2, p3 = _build_patches(_llm_client())
    with p1, p2, p3:
        first = await build_course_graph(session_factory, course_id)
        second = await build_course_graph(session_factory, course_id)

    assert first == second == 3

    async with session_factory() as db:
        nodes = (await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
        )).scalars().all()
        assert len(nodes) == 3  # No duplicate nodes from the rebuild


@pytest.mark.asyncio
async def test_e2e_no_content_builds_nothing(session_factory, course_id):
    p1, p2, p3 = _build_patches(_llm_client())
    with p1, p2, p3:
        count = await build_course_graph(session_factory, course_id)
    assert count == 0


# ── Graphusion fusion dedup ──


def _embedding_for(text: str) -> list[float]:
    """Deterministic fake embeddings: near-duplicates for 'Derivative*' names."""
    if text.startswith("Derivative"):
        return [1.0, 0.0]
    if text.startswith("The Derivative"):
        return [0.9, 0.1]  # cosine ≈ 0.994 vs "Derivative"
    return [0.0, 1.0]


@pytest.mark.asyncio
async def test_fusion_merges_duplicate_concepts():
    concepts = [
        {"name": "Derivative", "description": "Rate of change", "prerequisites": ["Limit"], "related": []},
        {"name": "The Derivative", "description": "The rate of change of a function", "prerequisites": [], "related": ["Slope"]},
        {"name": "Integral", "description": "Area under a curve", "prerequisites": [], "related": []},
    ]
    with patch(
        "services.memory.pipeline.generate_embedding",
        AsyncMock(side_effect=lambda text: _embedding_for(text)),
    ):
        fused = await _fuse_concepts(concepts)

    names = {c["name"] for c in fused}
    assert len(fused) == 2
    assert "Integral" in names
    # The duplicate pair merged into one concept with unioned relationships
    merged = next(c for c in fused if c["name"] != "Integral")
    assert set(merged["prerequisites"]) == {"Limit"}
    assert set(merged["related"]) == {"Slope"}


@pytest.mark.asyncio
async def test_fusion_threshold_is_configurable(monkeypatch):
    """LOOM_FUSION_SIMILARITY_THRESHOLD raises the bar: near-dupes stay separate."""
    from config import settings

    monkeypatch.setattr(settings, "loom_fusion_similarity_threshold", 0.999)
    assert _fusion_threshold() == 0.999

    concepts = [
        {"name": "Derivative", "description": "Rate of change", "prerequisites": [], "related": []},
        {"name": "The Derivative", "description": "Rate of change of a function", "prerequisites": [], "related": []},
    ]
    with patch(
        "services.memory.pipeline.generate_embedding",
        AsyncMock(side_effect=lambda text: _embedding_for(text)),
    ):
        fused = await _fuse_concepts(concepts)

    # cosine ≈ 0.994 < 0.999 → no merge under the stricter configured threshold
    assert len(fused) == 2


# ── Cross-course linking ──


@pytest.mark.asyncio
async def test_e2e_cross_course_linking(session_factory):
    course_a, course_b = uuid.uuid4(), uuid.uuid4()

    async with session_factory() as db:
        shared_a = KnowledgeNode(id=uuid.uuid4(), course_id=course_a, name="Eigenvalue", description="")
        shared_b = KnowledgeNode(id=uuid.uuid4(), course_id=course_b, name="Eigenvalue", description="")
        only_b = KnowledgeNode(id=uuid.uuid4(), course_id=course_b, name="Gradient Descent", description="")
        db.add(shared_a); db.add(shared_b); db.add(only_b)
        await db.commit()

        linked = await link_cross_course_concepts(db, course_b)
        await db.commit()
        assert linked == 1

        edges = (await db.execute(
            select(KnowledgeEdge).where(KnowledgeEdge.relation_type == "reinforces")
        )).scalars().all()
        pairs = {(e.source_id, e.target_id) for e in edges}
        # Bidirectional reinforces edges between the same-name concepts
        assert (shared_b.id, shared_a.id) in pairs
        assert (shared_a.id, shared_b.id) in pairs
        assert len(edges) == 2

        # Re-linking must not duplicate edges
        again = await link_cross_course_concepts(db, course_b)
        await db.commit()
        assert again == 0
