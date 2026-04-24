"""Learning-path progress helpers — Phase 16a T3 Python Paths UI.

Per critic C5 in ``plan/python_paths_ui_phase16a.md``, per-user path
progress is **derived** from ``PracticeResult`` rows rather than
materialised in a second table. These helpers encapsulate the two
queries the router needs:

* :func:`get_completed_task_ids` — the set of problem ids the user has
  answered correctly at least once (a card "counts as done" the first
  time it's green, regardless of subsequent reviews).
* :func:`get_room_task_counts` — batched total-tasks-per-room lookup, so
  the list endpoint doesn't issue one COUNT per room.

Kept here (not inline in the router) so unit tests can exercise the
aggregation without spinning up a FastAPI app, and so future callers
(capstone gate, path-complete notifications in P1) share the same
definition of "done".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.practice import PracticeProblem, PracticeResult


@dataclass(frozen=True, slots=True)
class RoomProgressSnapshot:
    """Derived per-room progress used by the paths router.

    ``task_total`` and ``task_complete`` are sourced from the same
    ``PracticeProblem`` / ``PracticeResult`` truth the list/detail
    endpoints already use. ``last_activity_at`` tracks the user's most
    recent answer in the room so the dashboard can resume the freshest
    in-progress mission without storing a separate "current mission"
    pointer.
    """

    task_total: int
    task_complete: int
    last_activity_at: datetime | None


async def get_completed_task_ids(
    db: AsyncSession, user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Return the set of ``problem_id`` values the user has answered correctly.

    A card is "complete" if the user has at least one ``PracticeResult``
    row with ``is_correct=True`` for it — the FSRS reset / re-review
    flow may later add more rows, but the first green answer is what
    marks the task done for the TryHackMe-style checkbox. DISTINCT at
    the DB keeps the payload small even when a card has been answered
    many times.
    """

    stmt = (
        select(PracticeResult.problem_id)
        .where(
            PracticeResult.user_id == user_id,
            PracticeResult.is_correct.is_(True),
        )
        .distinct()
    )
    rows = await db.execute(stmt)
    return {row[0] for row in rows.all()}


async def get_room_task_counts(
    db: AsyncSession, room_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Return ``{room_id: total_tasks}`` for the supplied room ids.

    Single ``COUNT(*) … GROUP BY path_room_id`` instead of per-room
    fan-out — the list endpoint calls this once with every room on the
    page. Rooms with zero mapped tasks are absent from the result
    (caller treats missing as 0); this matches the yaml-target vs
    actually-mapped-cards split the dashboard surfaces as "3/15 tasks".
    """

    if not room_ids:
        return {}
    stmt = (
        select(PracticeProblem.path_room_id, func.count(PracticeProblem.id))
        .where(PracticeProblem.path_room_id.in_(room_ids))
        .group_by(PracticeProblem.path_room_id)
    )
    rows = await db.execute(stmt)
    # SQLAlchemy returns the grouped column as the first tuple element;
    # it is never NULL here because the WHERE clause excludes orphans.
    return {row[0]: row[1] for row in rows.all()}


async def get_completed_task_counts_by_room(
    db: AsyncSession,
    user_id: uuid.UUID,
    room_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Return ``{room_id: distinct_correct_tasks}`` for the supplied rooms.

    A user may answer the same task correctly multiple times across
    FSRS reviews. ``COUNT(DISTINCT PracticeProblem.id)`` keeps each task
    worth exactly one checkbox in the mission progress UI.
    """

    if not room_ids:
        return {}

    stmt = (
        select(
            PracticeProblem.path_room_id,
            func.count(func.distinct(PracticeProblem.id)),
        )
        .join(PracticeResult, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeProblem.path_room_id.in_(room_ids),
            PracticeResult.user_id == user_id,
            PracticeResult.is_correct.is_(True),
        )
        .group_by(PracticeProblem.path_room_id)
    )
    rows = await db.execute(stmt)
    return {row[0]: row[1] for row in rows.all()}


async def get_room_last_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    room_ids: list[uuid.UUID],
) -> dict[uuid.UUID, datetime]:
    """Return the latest ``answered_at`` per room for the supplied user."""

    if not room_ids:
        return {}

    stmt = (
        select(
            PracticeProblem.path_room_id,
            func.max(PracticeResult.answered_at),
        )
        .join(PracticeResult, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeProblem.path_room_id.in_(room_ids),
            PracticeResult.user_id == user_id,
        )
        .group_by(PracticeProblem.path_room_id)
    )
    rows = await db.execute(stmt)
    return {row[0]: row[1] for row in rows.all()}


async def get_room_progress_snapshots(
    db: AsyncSession,
    user_id: uuid.UUID,
    room_ids: list[uuid.UUID],
) -> dict[uuid.UUID, RoomProgressSnapshot]:
    """Return live progress + last-activity metadata for every supplied room."""

    task_totals = await get_room_task_counts(db, room_ids)
    task_complete = await get_completed_task_counts_by_room(db, user_id, room_ids)
    last_activity = await get_room_last_activity(db, user_id, room_ids)

    return {
        room_id: RoomProgressSnapshot(
            task_total=task_totals.get(room_id, 0),
            task_complete=task_complete.get(room_id, 0),
            last_activity_at=last_activity.get(room_id),
        )
        for room_id in room_ids
    }


async def count_orphan_cards(db: AsyncSession) -> int:
    """Return the total number of practice problems without a ``path_room_id``.

    "Orphan" means a card lives in the content corpus but isn't yet
    attached to any path room — seeding only maps cards whose parent
    ``CourseContentTree.source_file`` matches a curated yaml URL, so
    the current live DB has 249 mapped / 332 orphan on a 581-card
    course. The dashboard surfaces this so Юрій knows there is still
    unmapped content without having to read the seed script's log.
    """

    stmt = select(func.count(PracticeProblem.id)).where(
        PracticeProblem.path_room_id.is_(None)
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


def _extract_first_block_text(blocks_json: object) -> str | None:
    """Best-effort: pull the first paragraph-ish text from a blocks-editor payload.

    ``blocks_json`` is a dict like ``{"blocks": [{"type": "paragraph",
    "content": "..."}, ...]}`` when present. Legacy rows only populate
    ``content`` (plain text) and leave ``blocks_json`` null. This helper
    runs only when ``content`` is null but ``blocks_json`` has data, so
    we can still surface a real intro instead of the seed placeholder.

    Returns ``None`` when the blob isn't a dict-with-blocks shape or
    when no block carries a non-empty text payload. Callers treat
    ``None`` as "no content found; fall back further".
    """

    if not isinstance(blocks_json, dict):
        return None
    blocks = blocks_json.get("blocks")
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if not isinstance(block, dict):
            continue
        # The editor stores free prose as ``paragraph`` / ``text`` blocks;
        # headings count too because the first heading of a chapter is
        # the intro line the user sees. We ignore code/image/list blocks
        # for the intro excerpt — the excerpt needs to be human-readable
        # prose, not a fenced code block rendered flat.
        block_type = block.get("type")
        if block_type in {"paragraph", "text", "heading", "h1", "h2", "h3"}:
            text = block.get("content") or block.get("text") or ""
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def _smart_truncate(text: str, max_chars: int) -> str:
    """Truncate at ``max_chars`` preserving the last word boundary.

    When the truncation would land mid-word we back up to the previous
    whitespace so the excerpt doesn't end on "Pyt" when the next char
    is "hon". If no whitespace exists in the window we take the hard
    cut — edge-case safety, not the common path.
    """

    text = text.strip()
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    last_space = window.rfind(" ")
    if last_space < max_chars * 0.6:
        # Backing up too far would lose half the window — just hard-cut.
        return window.rstrip()
    return window[:last_space].rstrip()


async def resolve_room_intro_excerpt(
    db: AsyncSession,
    room_id: uuid.UUID,
    *,
    placeholder: str | None = None,
    max_chars: int = 300,
) -> str | None:
    """Return the first 300-ish chars of real content for the room, or placeholder.

    Phase 16a seeded ``PathRoom.intro_excerpt`` with a string like
    ``"Topic: Loops. Grounded in 3 curated sources."`` so the UI never
    crashed on a null field. Slice 2 upgrades this to real lesson text:
    the first non-empty ``CourseContentTree.content`` (or first prose
    block inside ``blocks_json``) referenced by any ``PracticeProblem``
    mapped to this room.

    Resolution order
    ----------------
    1. Any mapped task with a ``content_node_id`` pointing to a content
       tree node that has non-null ``content`` → first ``max_chars`` of
       that node's content (word-boundary safe).
    2. Same join, but ``content`` null and ``blocks_json`` has prose
       blocks → first prose block's text, truncated.
    3. Nothing usable → the caller-supplied ``placeholder`` (typically
       ``room.intro_excerpt`` so the seed string survives).
    4. Placeholder is ``None`` → return ``None``.

    The SQL filter ``content IS NOT NULL OR blocks_json IS NOT NULL``
    prevents a room whose first-ordered mapped task points at a legacy
    "shell" node (metadata only) from resolving to NULL when later nodes
    have real prose (critic C2).
    """

    stmt = (
        select(CourseContentTree.content, CourseContentTree.blocks_json)
        .join(
            PracticeProblem,
            PracticeProblem.content_node_id == CourseContentTree.id,
        )
        .where(
            PracticeProblem.path_room_id == room_id,
            or_(
                CourseContentTree.content.is_not(None),
                CourseContentTree.blocks_json.is_not(None),
            ),
        )
        .order_by(
            CourseContentTree.order_index.asc(),
            CourseContentTree.id.asc(),
        )
        .limit(5)
    )
    rows = (await db.execute(stmt)).all()
    for content, blocks_json in rows:
        if isinstance(content, str) and content.strip():
            return _smart_truncate(content, max_chars)
        block_text = _extract_first_block_text(blocks_json)
        if block_text:
            return _smart_truncate(block_text, max_chars)

    return placeholder


async def sample_orphan_cards(db: AsyncSession, limit: int = 10) -> list[dict]:
    """Return up to ``limit`` orphan problems as ``{id, question}`` dicts.

    Used by ``GET /api/paths/orphans`` to power the dashboard caption —
    the first ten orphan card titles are enough context for Юрій to
    recognise a cluster ("все з розділу X") without shipping the full
    332-row payload. ``question`` is the flashcard front / MC prompt;
    we trim to the first 80 chars so long free-response prompts don't
    dominate the response.
    """

    stmt = (
        select(PracticeProblem.id, PracticeProblem.question)
        .where(PracticeProblem.path_room_id.is_(None))
        .order_by(PracticeProblem.created_at.asc())
        .limit(limit)
    )
    rows = await db.execute(stmt)
    return [
        {
            "id": str(row[0]),
            "title": (row[1] or "").strip()[:80],
        }
        for row in rows.all()
    ]


__all__ = [
    "count_orphan_cards",
    "get_completed_task_counts_by_room",
    "get_completed_task_ids",
    "get_room_last_activity",
    "get_room_progress_snapshots",
    "get_room_task_counts",
    "resolve_room_intro_excerpt",
    "RoomProgressSnapshot",
    "sample_orphan_cards",
]
