"""Persist a generated :class:`Syllabus` into the knowledge-graph tables.

Part of §14.5 v2.1 (URL → auto-curriculum), task T2.

T1 produces an in-memory :class:`schemas.curriculum.Syllabus` — a validated
topic roadmap with a topologically sorted suggested path. T2's job is to
write that roadmap into the existing ``knowledge_nodes`` /
``knowledge_edges`` tables **plus** record the path in the owning
``courses.metadata_['roadmap']`` JSONB blob, all inside a single
transaction.

Design notes
------------
* **Idempotent regeneration.** Re-ingesting the same URL must not produce
  duplicated nodes. Before inserting, we delete every ``KnowledgeNode``
  row for this ``course_id`` whose ``metadata_['source']`` equals
  ``"syllabus_builder"``. Deletion is scoped to (course AND source tag) so
  LOOM-extracted or hand-curated nodes in the same course are never
  touched. ``ondelete="CASCADE"`` on ``KnowledgeEdge.(source_id,
  target_id)`` means edges clean themselves up.
* **Cross-DB JSON filtering.** SQLite's ``JSON`` column doesn't support the
  PostgreSQL ``->>`` operator through the ``CompatJSONB`` alias, and the
  project runs on SQLite locally. We therefore fetch candidate nodes in
  Python, filter by ``metadata_.get("source")``, and bulk-delete by the
  collected IDs. On realistic course sizes (<~200 KG nodes) this is cheap.
* **Transaction scoping.** All writes (delete + inserts + course update)
  share the caller's session. We flush after each batch to make IDs
  visible but never commit — the caller commits once at the very end, so a
  crash mid-way leaves the course in its pre-call state.
* **No timezone libs.** We pick ``datetime.now(timezone.utc).isoformat()``
  for the ``generated_at`` timestamp — stdlib-only, ISO-8601 w/ offset,
  matches what :class:`sqlalchemy.DateTime` round-trips elsewhere in the
  code base.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.knowledge_graph import KnowledgeEdge, KnowledgeNode
from schemas.curriculum import Syllabus

logger = logging.getLogger(__name__)


SYLLABUS_SOURCE_TAG = "syllabus_builder"
"""Marker placed in ``KnowledgeNode.metadata_['source']`` to identify
syllabus-generated nodes. Scoping deletions by this tag is what keeps
idempotent regeneration from nuking LOOM-extracted or hand-curated
nodes in the same course."""

ROADMAP_BUILDER_VERSION = "v2.1"


async def _collect_existing_syllabus_node_ids(
    db: AsyncSession, course_id: uuid.UUID
) -> list[uuid.UUID]:
    """Return the IDs of existing syllabus-sourced nodes in this course.

    Filters in Python so the query works identically on SQLite (used
    locally) and Postgres. For realistic course sizes (<200 KG nodes) this
    is cheap compared to the LLM call that precedes it.
    """

    stmt = select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        row.id
        for row in rows
        if (row.metadata_ or {}).get("source") == SYLLABUS_SOURCE_TAG
    ]


async def _delete_existing_syllabus_nodes(
    db: AsyncSession, course_id: uuid.UUID
) -> int:
    """Delete syllabus-sourced knowledge nodes for this course.

    Deletion is scoped to (course AND source tag). Edges cascade via the
    FK ``ondelete="CASCADE"`` on ``KnowledgeEdge.(source_id, target_id)``.

    Returns the count deleted (for logging / test assertions).
    """

    node_ids = await _collect_existing_syllabus_node_ids(db, course_id)
    if not node_ids:
        return 0

    await db.execute(sa_delete(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids)))
    await db.flush()
    return len(node_ids)


async def _insert_nodes(
    db: AsyncSession, course_id: uuid.UUID, syllabus: Syllabus
) -> dict[str, uuid.UUID]:
    """Create a ``KnowledgeNode`` per ``SyllabusNode``. Return slug→id map."""

    slug_to_id: dict[str, uuid.UUID] = {}
    for syllabus_node in syllabus.nodes:
        kn = KnowledgeNode(
            id=uuid.uuid4(),
            course_id=course_id,
            name=syllabus_node.topic,
            description=syllabus_node.blurb,
            metadata_={
                "source": SYLLABUS_SOURCE_TAG,
                "slug": syllabus_node.slug,
            },
        )
        db.add(kn)
        slug_to_id[syllabus_node.slug] = kn.id
    await db.flush()
    return slug_to_id


async def _insert_edges(
    db: AsyncSession,
    syllabus: Syllabus,
    slug_to_id: dict[str, uuid.UUID],
) -> int:
    """Create prerequisite edges. Direction: child → parent (source=child).

    That matches the plan's semantics: "a prerequisite edge points FROM
    the topic that depends ON a prerequisite TO the prerequisite". I.e.
    ``depends_on`` expresses inbound dependencies, so an edge
    ``(source=dependent, target=prerequisite, relation_type='prerequisite')``
    reads naturally as "dependent requires prerequisite".

    Returns the edge count (for logging / test assertions).
    """

    edge_count = 0
    for syllabus_node in syllabus.nodes:
        for prereq_slug in syllabus_node.depends_on:
            source_id = slug_to_id[syllabus_node.slug]
            target_id = slug_to_id[prereq_slug]
            edge = KnowledgeEdge(
                id=uuid.uuid4(),
                source_id=source_id,
                target_id=target_id,
                relation_type="prerequisite",
                weight=1.0,
            )
            db.add(edge)
            edge_count += 1
    await db.flush()
    return edge_count


async def _update_course_roadmap_metadata(
    db: AsyncSession,
    course_id: uuid.UUID,
    syllabus: Syllabus,
    slug_to_id: dict[str, uuid.UUID],
) -> None:
    """Record the path + builder version + timestamp on ``courses.metadata_``.

    We fetch the course, merge ``roadmap`` into its existing metadata dict
    (preserving other keys like ``spaceLayout``), and issue a targeted
    ``UPDATE`` rather than relying on ORM flush — JSON columns don't
    auto-detect in-place mutation reliably across SQLite/Postgres.
    """

    roadmap_payload = {
        "builder_version": ROADMAP_BUILDER_VERSION,
        "path": [str(slug_to_id[slug]) for slug in syllabus.suggested_path],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if course is None:
        logger.warning(
            "persist_syllabus: course %s vanished mid-call; skipping metadata update",
            course_id,
        )
        return

    merged_metadata = {**(course.metadata_ or {}), "roadmap": roadmap_payload}
    await db.execute(
        sa_update(Course)
        .where(Course.id == course_id)
        .values(metadata_=merged_metadata)
    )
    await db.flush()


async def persist_syllabus(
    db: AsyncSession, course_id: uuid.UUID, syllabus: Syllabus
) -> dict[str, int]:
    """Persist a validated :class:`Syllabus` for a course.

    Single-transaction side effects (caller owns the commit):

    1. Delete previously-generated syllabus nodes in this course
       (idempotent re-run).
    2. Insert one :class:`KnowledgeNode` per ``syllabus.nodes`` entry.
    3. Insert one :class:`KnowledgeEdge` per ``depends_on`` relation, with
       ``relation_type="prerequisite"`` (source=dependent, target=prereq).
    4. Update ``courses.metadata_['roadmap']`` with ``builder_version``,
       ordered ``path`` of node IDs, and ``generated_at`` ISO-8601 UTC.

    The function never commits or rolls back; the caller (T2 pipeline
    background task) opens its own session and commits once at the end.

    Args:
        db: Async SQLAlchemy session. All writes go through it.
        course_id: UUID of the course whose roadmap should be replaced.
        syllabus: Validated syllabus from :func:`build_syllabus`.

    Returns:
        A dict of counts — ``{"deleted_nodes": N, "inserted_nodes": N,
        "inserted_edges": N}`` — handy for logging + test assertions.
    """

    deleted_nodes = await _delete_existing_syllabus_nodes(db, course_id)
    slug_to_id = await _insert_nodes(db, course_id, syllabus)
    inserted_edges = await _insert_edges(db, syllabus, slug_to_id)
    await _update_course_roadmap_metadata(db, course_id, syllabus, slug_to_id)

    counts = {
        "deleted_nodes": deleted_nodes,
        "inserted_nodes": len(slug_to_id),
        "inserted_edges": inserted_edges,
    }
    logger.info(
        "persist_syllabus: course=%s deleted=%d nodes, inserted=%d nodes, %d edges",
        course_id,
        deleted_nodes,
        len(slug_to_id),
        inserted_edges,
    )
    return counts


__all__ = [
    "persist_syllabus",
    "SYLLABUS_SOURCE_TAG",
    "ROADMAP_BUILDER_VERSION",
]
