"""Welcome-back compute service — Phase 14 T4 ADHD UX.

Single public coroutine :func:`compute_welcome_back` backs
``GET /api/sessions/welcome-back``. The endpoint powers the Story 4
"I-am-back" modal: when the learner has been away for several days,
the dashboard greets them calmly instead of shaming them with a red
overdue-count badge.

Shape of the return value — :class:`schemas.sessions.WelcomeBackResponse`:

* ``gap_days`` — integer days since the learner's last answered problem,
  computed in UTC. ``None`` when the user has zero
  :class:`models.practice.PracticeResult` rows (the frontend suppresses
  the modal for fresh accounts so the onboarding flow stays in charge).
* ``last_practice_at`` — UTC-aware ``datetime`` of the most recent
  answer, or ``None`` when there is no history.
* ``top_mastered_concepts`` — titles of up to three content nodes the
  learner has most recently answered correctly. Drives the
  "Review what I last learned" path (Story 4 option c). Empty list when
  the user has no correct-answer history.
* ``overdue_count`` — count of distinct practice problems whose FSRS
  ``next_review_at`` is strictly in the past. The modal renders this as
  a soft footnote ("Your queue has N overdue cards") — no red badge,
  no count inflation.

Design notes
------------
* **Pure compute, zero writes.** The Phase 14 critic ruling pinned the
  migration budget at one (freeze_tokens), so welcome-back must derive
  everything from existing tables on read. No caching either — the
  query set is tiny (three indexed selects) and the endpoint is only
  hit once per dashboard mount.

* **Concept slug fallback.** The original plan specified
  ``concept_slug`` but no such column exists in
  :class:`models.practice.PracticeProblem`. We fall back to
  ``content_node_id`` → :attr:`models.content.CourseContentTree.title`.
  Rows with ``content_node_id IS NULL`` are skipped — they represent
  free-standing drills with no structural home, so there's no stable
  concept label to surface.

* **Timezone normalisation.** This module is explicitly on the
  regression path for the 2026-04-23 naive-vs-aware bug — SQLite strips
  tzinfo on round-trip even when the column is declared
  ``DateTime(timezone=True)``. We funnel every DB datetime through
  :func:`libs.datetime_utils.as_utc` before comparing against
  :func:`utcnow`, so naive and aware values both yield the same
  ``gap_days``. Never compare raw DB datetimes against ``now`` directly.

* **Single-user note.** The service takes ``user_id`` explicitly — even
  under single-user local mode the queries all filter by ``user_id`` so
  a future multi-user flip doesn't quietly start leaking another
  tenant's history into the welcome-back payload.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import as_utc, utcnow
from models.content import CourseContentTree
from models.practice import PracticeProblem, PracticeResult
from models.progress import LearningProgress
from schemas.sessions import WelcomeBackResponse


TOP_MASTERED_LIMIT: int = 3
"""Hard cap on the ``top_mastered_concepts`` list. Three is the count
the Story 4 UI copies ("review what I last learned"); surfacing more
would push the modal past its comfortable height and defeat the calm
tone the welcome-back flow is meant to hit."""


async def _query_last_practice_at(
    db: AsyncSession, user_id: uuid.UUID
) -> PracticeResult | None:
    """Return the learner's most recent ``PracticeResult`` row, or ``None``.

    We fetch the whole row (not just ``MAX(answered_at)``) so the
    ``answered_at`` we return to the caller is the same value the DB
    actually holds — the aggregate form would still round-trip through
    SQLite's naive-datetime handling identically, but pulling the row
    keeps the flow explicit and matches the Phase 13/14 service style.
    """

    stmt: Select = (
        select(PracticeResult)
        .where(PracticeResult.user_id == user_id)
        .order_by(PracticeResult.answered_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _query_top_mastered_titles(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int
) -> list[str]:
    """Titles of up to ``limit`` most recently-mastered content nodes.

    "Mastered" here means: the learner's most recent
    :class:`models.practice.PracticeResult` for that content node was
    ``is_correct = True``. A subsequent wrong answer on the same node
    demotes it out of the list immediately — which matches the Story 4
    UX: surfacing a concept the learner just fumbled would undermine
    the "here's what you already know" framing.

    Implementation:

    1. For each ``content_node_id`` the learner has answered, find the
       ``answered_at`` of the latest result via a per-node aggregate.
    2. Join back to the result row at that timestamp and keep the ones
       where ``is_correct = True``.
    3. Sort by the winning ``answered_at`` descending (most-recent
       mastery first) and take ``limit``.
    4. Resolve each ``content_node_id`` to its
       :attr:`models.content.CourseContentTree.title`.

    Rows with ``content_node_id IS NULL`` are filtered out — they carry
    no stable concept label and would render as blank entries in the
    modal.
    """

    # Step 1 — latest answered_at per content_node, per user.
    latest_per_node = (
        select(
            PracticeProblem.content_node_id.label("cn_id"),
            func.max(PracticeResult.answered_at).label("max_at"),
        )
        .join(PracticeProblem, PracticeProblem.id == PracticeResult.problem_id)
        .where(
            PracticeResult.user_id == user_id,
            PracticeProblem.content_node_id.is_not(None),
        )
        .group_by(PracticeProblem.content_node_id)
        .subquery()
    )

    # Step 2 + 3 — join back to the row, keep correct ones, sort by
    # recency. We deliberately pull ``distinct`` content_node_ids here:
    # if two problems under the same node happen to share the exact
    # ``max_at`` timestamp (rare but possible on millisecond-precision
    # stores), we still want one row per node.
    stmt = (
        select(
            PracticeProblem.content_node_id,
            latest_per_node.c.max_at,
        )
        .join(
            PracticeProblem,
            PracticeProblem.content_node_id == latest_per_node.c.cn_id,
        )
        .join(
            PracticeResult,
            (PracticeResult.problem_id == PracticeProblem.id)
            & (PracticeResult.answered_at == latest_per_node.c.max_at),
        )
        .where(
            PracticeResult.user_id == user_id,
            PracticeResult.is_correct.is_(True),
        )
        .order_by(latest_per_node.c.max_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    # Collapse by content_node_id preserving first-seen (most-recent)
    # order — guards against the millisecond-tie case above.
    seen: set[uuid.UUID] = set()
    ordered_ids: list[uuid.UUID] = []
    for cn_id, _ in rows:
        if cn_id is None or cn_id in seen:
            continue
        seen.add(cn_id)
        ordered_ids.append(cn_id)
        if len(ordered_ids) >= limit:
            break

    if not ordered_ids:
        return []

    # Step 4 — resolve titles. ``in_()`` then re-sort in Python because
    # SQL ORDER BY on ``CASE WHEN id = :x`` blows up the query plan and
    # the list is at most 3 entries.
    title_stmt = select(CourseContentTree.id, CourseContentTree.title).where(
        CourseContentTree.id.in_(ordered_ids)
    )
    title_rows = (await db.execute(title_stmt)).all()
    title_by_id = {row_id: title for row_id, title in title_rows}
    return [title_by_id[cn_id] for cn_id in ordered_ids if cn_id in title_by_id]


async def _query_overdue_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Count distinct problems with ``next_review_at`` strictly in the past.

    Mirrors the rank-0 predicate in :func:`services.daily_plan.select_daily_plan`
    ("overdue = next_review_at < now"). Scoped to the caller's
    ``user_id`` so multi-tenant mode stays correct. ``DISTINCT`` is
    belt-and-braces — ``learning_progress`` should have at most one row
    per ``(user_id, content_node_id)``, but counting distinct
    ``problem`` joins keeps the number honest even if a future index
    change introduces dupes.
    """

    now = utcnow()
    stmt = (
        select(func.count(distinct(PracticeProblem.id)))
        .select_from(LearningProgress)
        .join(
            PracticeProblem,
            PracticeProblem.content_node_id == LearningProgress.content_node_id,
        )
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.next_review_at.is_not(None),
            LearningProgress.next_review_at < now,
        )
    )
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def compute_welcome_back(
    db: AsyncSession, user_id: uuid.UUID
) -> WelcomeBackResponse:
    """Return the welcome-back payload for ``user_id``.

    Args:
        db: Active async SQLAlchemy session. Caller owns the
            transaction — this function does not commit.
        user_id: Learner whose history we're summarising.

    Returns:
        A :class:`schemas.sessions.WelcomeBackResponse`:

        * ``gap_days`` — ``(now_utc.date() - last_answered_at.date()).days``.
          ``None`` iff the user has never answered a problem.
        * ``last_practice_at`` — UTC-aware ``datetime`` of the most
          recent answer, or ``None``.
        * ``top_mastered_concepts`` — up to three
          :attr:`CourseContentTree.title` values (most-recent mastery
          first). Empty list when there is no correct-answer history or
          all correct answers were against ``content_node_id IS NULL``
          problems.
        * ``overdue_count`` — ``COUNT(DISTINCT problem_id)`` where the
          learner's FSRS ``next_review_at`` is strictly in the past.

    Notes:
        The DB-side datetimes are normalised via
        :func:`libs.datetime_utils.as_utc` before comparing against
        :func:`libs.datetime_utils.utcnow`, so a SQLite round-trip that
        strips tzinfo does not blow up with
        ``TypeError: can't compare offset-naive and offset-aware``.
    """

    last_row = await _query_last_practice_at(db, user_id)
    if last_row is None:
        last_practice_at = None
        gap_days: int | None = None
    else:
        last_practice_at = as_utc(last_row.answered_at)
        now_utc = utcnow()
        gap_days = (now_utc.date() - last_practice_at.date()).days

    top_mastered = await _query_top_mastered_titles(
        db, user_id, limit=TOP_MASTERED_LIMIT
    )
    overdue_count = await _query_overdue_count(db, user_id)

    return WelcomeBackResponse(
        gap_days=gap_days,
        last_practice_at=last_practice_at,
        top_mastered_concepts=top_mastered,
        overdue_count=overdue_count,
    )


__all__ = ["TOP_MASTERED_LIMIT", "compute_welcome_back"]
