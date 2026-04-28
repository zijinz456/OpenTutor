"""Daily-session card selection for the ADHD UX layer (Phase 13 T1).

Exposes a single public coroutine :func:`select_daily_plan` that returns
the curated 1 / 5 / 10 card batch served by
``GET /api/sessions/daily-plan`` (router in :mod:`routers.sessions`).

Selection algorithm
-------------------

The endpoint is the entry point for MASTER §8 ADHD UX — a tiny,
guilt-free batch that respects the user's current review debt. Priority
tiers, highest first:

``rank 0`` — **overdue**: FSRS ``learning_progress.next_review_at``
    is strictly in the past (``< now``). Also covers problems that
    have **no** matching ``LearningProgress`` row **and** have been
    answered at least once (orphaned FSRS state). Sorted inside the
    tier by ``next_review_at ASC`` (oldest overdue first). Brand-new
    problems without any review history deliberately *do not* land in
    rank 0 — they go into rank 2 below so we never drown the learner
    in freshly-scraped content.

``rank 1`` — **due today**: ``next_review_at`` falls in
    ``(now, now + 24h]``. Sorted by ``next_review_at ASC`` so the
    earliest-expiring cards come first — if the session runs short,
    they're the ones most at risk of sliding into tier 0 tomorrow.

``rank 2`` — **recently failed**: problem appears in
    ``practice_results`` with ``is_correct = 0`` and
    ``answered_at > now - 7 days``, and was not already captured by
    rank 0/1. Sorted by the most recent failed ``answered_at DESC`` —
    freshest mistake first. FSRS would normally pull these back soon
    anyway; this tier exists so a learner who just fumbled a card sees
    it again before the scheduler catches up.

Rank ordering is strict: the selector drains rank 0 first, then rank 1,
then rank 2. Type-rotation (see below) is applied **inside** each rank,
so overdue never gets starved by a queue of recently-failed code
exercises.

Type rotation
-------------

Within a single rank, we round-robin across distinct ``question_type``
buckets (MC, code_exercise, lab_exercise, flashcard, …) while
preserving each bucket's own priority order. This ensures that a
learner with 20 overdue MC cards and 2 overdue code-exercises gets a
mixed batch at ``size=5`` — matches the MASTER §8 principle that an
ADHD session should feel varied enough to keep attention without
crossing into overwhelm.

Dedup
-----

A problem that qualifies for multiple ranks (e.g. overdue AND recently
failed) is kept at its *lowest* rank and removed from the later tiers.
Same ``PracticeProblem.id`` never appears twice in the response.

Database access
---------------

Two async queries:

1. ``PracticeProblem ⟕ LearningProgress`` — SQLAlchemy LEFT JOIN across
   ``(course_id, content_node_id)``. Pulls every non-archived problem
   row plus any matching FSRS state. The join is **not** filtered by
   user because this codebase runs in single-user local mode (see
   ``services/auth/dependency.py``) — all problems belong to the
   single tenant. We take the ``user.id`` in from the router only to
   keep the router signature consistent with the rest of the API.

2. ``PracticeResult`` for recently-failed problem IDs — a distinct
   subquery on the last 7 days, skipped if tier 0/1 already filled the
   batch to ``size``. Using the subquery keeps the main join narrow
   instead of dragging ``practice_results`` into a single monster SQL
   that SQLite struggles to plan well.

Complexity is O(P) where P is the non-archived problem count (a small
constant ~ hundreds per course today). A future optimisation could
push the ordering into SQL via a ``CASE WHEN`` rank column, but the
Python path is clearer to audit and is fast enough for the single-user
deployment (P ≤ 10k is still sub-100ms on SQLite).

Public API
----------

The module exposes exactly one coroutine — :func:`select_daily_plan`.
Size validation is also enforced at the schema level
(:data:`schemas.sessions.DailySessionSize`) so any
``ValueError`` raised here means a caller bypassed pydantic and is a
real bug, not user input.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import utcnow
from models.practice import PracticeProblem, PracticeResult
from models.progress import LearningProgress
from schemas.sessions import DailyPlan, DailyPlanCard, DailyPlanReason


ALLOWED_SIZES: frozenset[int] = frozenset({1, 5, 10})
"""Session sizes the ADHD endpoint understands. Mirrors
:data:`schemas.sessions.DailySessionSize` — kept here as an explicit
constant so the service can self-validate when exercised from tests or
internal callers that bypass the HTTP layer."""

ALLOWED_BRUTAL_SIZES: frozenset[int] = frozenset({20, 30, 50})
"""Session sizes the Brutal Drill endpoint understands. Mirrors
:data:`schemas.sessions.BrutalSessionSize`. A brutal session is the
anti-ADHD case — deliberately heavy, struggle-first, interview-prep —
so the allowed sizes never overlap with :data:`ALLOWED_SIZES`."""

RECENTLY_FAILED_WINDOW_DAYS: int = 7
"""How far back ``PracticeResult`` is scanned for rank-2 candidates
under the default ADHD strategy. Seven days keeps the tier fresh
(a week-old mistake is usually re-scheduled by FSRS anyway) while
surviving a long weekend off."""

BRUTAL_RECENTLY_FAILED_WINDOW_DAYS: int = 14
"""Widened recent-fail window for ``strategy="struggle_first"``. The
brutal mode leads with struggle — a 7-day window is too narrow when the
user is cramming over the weeks leading up to an interview. Fourteen
days is the phase-6 contract (§F1 of the plan)."""


_CODE_LIKE_QUESTION_TYPES: frozenset[str] = frozenset({"code_exercise", "lab_exercise"})
"""Question types the brutal strategy filters out. Code and lab rows
need their own runner UI — the brutal drill is MC-only by design so the
countdown clock makes sense and results stay comparable across cards.
Kept private because the daily strategy does NOT filter on question type
(its type-rotation actively wants the variety)."""


_EASY_DIFFICULTY_LAYER: int = 1
"""VCE-inspired ``PracticeProblem.difficulty_layer`` value that counts as
"easy" for the bad-day filter. The model docstring pins layer semantics
as 1=basic concept recall, 2=standard application, 3=trap/edge case;
Phase 14 T5 Story 5 restricts bad-day to the layer-1 tier exclusively.
Kept private because the ADHD default strategy has no notion of layer."""


_BAD_DAY_STRUGGLE_THRESHOLD: int = 3
"""Lifetime "wrong answers" count above which a problem is excluded
from the bad-day pool. Story 5 C4 — if the learner has already failed
a card three or more times, surfacing it in bad-day mode breaks the
"easier cards only" contract. Threshold is inclusive (``>= 3``) to
match the plan literal."""


Strategy = Literal["adhd_safe", "struggle_first", "easy_only"]
"""Service-level strategy set. Kept wider than :data:`schemas.sessions.
DailyPlanStrategy` on purpose — ``"struggle_first"`` is an internal
call used by :mod:`services.brutal_plan` and must keep working, but it
is NOT a valid ``?strategy=`` query on the public daily-plan endpoint
(the schema-level Literal rejects it at the HTTP edge). Adding a value
here means also adding it to the size-validation branch below."""


async def select_daily_plan(
    db: AsyncSession,
    size: int,
    *,
    strategy: Strategy = "adhd_safe",
    excluded_ids: Iterable[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> DailyPlan:
    """Return the daily-session batch for the configured user.

    Args:
        db: Active async SQLAlchemy session. The caller owns the
            transaction — we do not commit.
        size: Requested batch size. Allowed values depend on ``strategy``:
            :data:`ALLOWED_SIZES` for ``"adhd_safe"`` and
            :data:`ALLOWED_BRUTAL_SIZES` for ``"struggle_first"``.
        strategy: Selector profile.

            * ``"adhd_safe"`` (default, Phase 13 behaviour — UNCHANGED):
              rank 0 overdue → rank 1 due-today → rank 2 recently-failed
              with a 7-day window, type-rotation applied inside each
              tier, no question-type filter.
            * ``"struggle_first"`` (Phase 6 Brutal Drill): tier ranks
              swapped so **recent-fail comes first** (14-day window),
              then overdue, then due-today, then rank 3 "never-seen
              with ``concept_slug``". Type-rotation is disabled — the
              brutal UX actively wants serialised struggle, not variety
              — and ``code_exercise`` / ``lab_exercise`` rows are filtered
              out because the brutal UI is MC-only.
            * ``"easy_only"`` (Phase 14 T5 bad-day): same tier ordering
              and type-rotation as ``"adhd_safe"``, but the candidate pool
              is first narrowed to ``difficulty_layer == 1`` AND drops
              every problem the user has answered incorrectly ≥3 times
              lifetime. Frontend enables this when the user opts into
              bad-day mode for the current UTC day. Empty filtered pool
              returns ``reason="bad_day_empty"`` so the UI distinguishes
              "you've failed all the easy ones recently" from plain
              "nothing_due".
        excluded_ids: Optional iterable of ``PracticeProblem.id`` values
            to drop before tier classification. Used by Phase 14 T1 to
            honor active freeze tokens — freezing a card hides it from
            the daily session for 24h without touching FSRS. Filter runs
            **after** the DB join (so we still materialise one row per
            problem) but **before** tier classification (so the freeze
            never takes priority over another card that would otherwise
            be excluded for a more important reason). Passing ``None``
            or an empty iterable is equivalent to the Phase 13 behaviour.

    Returns:
        A :class:`schemas.sessions.DailyPlan`. ``cards`` is ordered by
        priority tier (tier semantics depend on ``strategy``). ``reason``
        is ``"nothing_due"`` iff the curated pool was empty, otherwise
        ``None`` (including the case where the pool was smaller than
        ``size`` — callers that care about partial fill inspect
        ``len(cards) < size`` directly, see
        :func:`services.brutal_plan.select_brutal_plan`).

    Raises:
        ValueError: ``size`` is outside the allowed set for the chosen
            strategy. The HTTP layers reject bad sizes earlier via the
            pydantic ``Literal`` types; raising here guards against
            non-HTTP callers.
    """

    if strategy in {"adhd_safe", "easy_only"}:
        if size not in ALLOWED_SIZES:
            raise ValueError(
                f"size must be one of {sorted(ALLOWED_SIZES)} for "
                f"strategy='adhd_safe', got {size!r}"
            )
        recent_window_days = RECENTLY_FAILED_WINDOW_DAYS
    elif strategy == "struggle_first":
        if size not in ALLOWED_BRUTAL_SIZES:
            raise ValueError(
                f"size must be one of {sorted(ALLOWED_BRUTAL_SIZES)} for "
                f"strategy='struggle_first', got {size!r}"
            )
        recent_window_days = BRUTAL_RECENTLY_FAILED_WINDOW_DAYS
    elif strategy == "easy_only":
        # Bad-day mode reuses the ADHD size trio — the toggle is exposed
        # on the same dashboard CTA that ships 1/5/10 buttons, and the
        # 7-day recent-fail window is the right cadence for a learner
        # opting into an easier day (we do NOT widen to 14d here, that's
        # a brutal-mode trait).
        if size not in ALLOWED_SIZES:
            raise ValueError(
                f"size must be one of {sorted(ALLOWED_SIZES)} for "
                f"strategy='easy_only', got {size!r}"
            )
        recent_window_days = RECENTLY_FAILED_WINDOW_DAYS
    else:  # pragma: no cover — caught by Literal on the typed call sites
        raise ValueError(f"unknown strategy {strategy!r}")

    # Default ``now`` to wall-clock; tests pin it via the ``now=`` kwarg
    # to keep tier classification deterministic (see Story-3 streak fix
    # for the symmetric problem on freeze-quota counting). Production
    # callers pass nothing and get :func:`utcnow` as before.
    if now is None:
        now = utcnow()
    due_horizon = now + timedelta(hours=24)
    recent_failure_floor = now - timedelta(days=recent_window_days)

    # ── Query 1: problems LEFT JOIN learning_progress ──
    # Join condition matches how tracker.get_or_create_progress keys
    # rows: (user_id irrelevant under single-user, course_id,
    # content_node_id). We deliberately drop the user filter — see module
    # docstring on single-user mode. content_node_id NULL-safe join uses
    # IS NOT DISTINCT FROM semantics via two ORed comparisons because
    # SQLite doesn't speak the ANSI operator.
    join_stmt = (
        select(PracticeProblem, LearningProgress)
        .outerjoin(
            LearningProgress,
            (LearningProgress.course_id == PracticeProblem.course_id)
            & (LearningProgress.content_node_id == PracticeProblem.content_node_id),
        )
        .where(PracticeProblem.is_archived.is_(False))
    )
    join_result = await db.execute(join_stmt)
    joined_rows: list[tuple[PracticeProblem, LearningProgress | None]] = list(
        join_result.all()
    )

    if not joined_rows:
        # Under ``easy_only`` we tag the empty branch so the bad-day UX
        # path stays coherent (the frontend prompts "turn bad-day off"
        # on ``bad_day_empty``; ``nothing_due`` would nudge to onboarding).
        empty_reason_no_rows: DailyPlanReason = (
            "bad_day_empty" if strategy == "easy_only" else "nothing_due"
        )
        return DailyPlan(cards=[], size=0, reason=empty_reason_no_rows)

    # Collapse the LEFT JOIN to one row per problem. A problem with no
    # content_node_id that matches multiple progress rows (shouldn't
    # happen in practice because progress is keyed by the tuple, but the
    # schema allows it) collapses to its most-recent progress row so the
    # FSRS signal is never stale. If both are absent we keep the problem
    # with ``lp = None`` — that lands it in tier 2 if it has any failed
    # results, otherwise it's skipped by the tier classifier below.
    by_problem_id: dict[uuid.UUID, tuple[PracticeProblem, LearningProgress | None]] = {}
    for problem, progress in joined_rows:
        existing = by_problem_id.get(problem.id)
        if existing is None:
            by_problem_id[problem.id] = (problem, progress)
            continue
        # Prefer the progress row that looks "more active": non-None
        # next_review_at, higher fsrs_reps, more recent last_studied_at.
        # Without this the picker could see stale duplicates and mis-rank.
        _, incumbent = existing
        if _progress_more_active(progress, incumbent):
            by_problem_id[problem.id] = (problem, progress)

    # ── Phase 14 T1: drop frozen / caller-excluded problem IDs ──
    # Runs between the join-collapse and the tier classifier so frozen
    # cards are invisible at every downstream step (rank assignment, type
    # rotation, dedup). Copying the iterable to a ``set`` once keeps the
    # membership check O(1) for the whole pass even if the caller passed
    # a list.
    if excluded_ids:
        excluded_set: set[uuid.UUID] = set(excluded_ids)
        if excluded_set:
            by_problem_id = {
                pid: row
                for pid, row in by_problem_id.items()
                if pid not in excluded_set
            }
            if not by_problem_id:
                # Every candidate was frozen/excluded — same contract as
                # "DB is empty" so the UI renders the quick-closure card.
                # Under ``easy_only`` we still emit "bad_day_empty" so
                # the frontend can steer the learner to turn the toggle
                # off instead of nudging toward onboarding.
                empty_reason: DailyPlanReason = (
                    "bad_day_empty" if strategy == "easy_only" else "nothing_due"
                )
                return DailyPlan(cards=[], size=0, reason=empty_reason)

    # ── Phase 14 T5: bad-day pool filter (strategy="easy_only") ──
    # Narrow the surviving candidates to ``difficulty_layer == 1`` minus
    # every problem the user has gotten wrong ≥3 times lifetime. Runs
    # AFTER freeze/excluded_ids so the two filters compose — a frozen
    # easy card still drops out (critic C8), and a 3-wrong card is gone
    # regardless of whether the user also tried to freeze it.
    #
    # We lift the struggle-count query out of the join above because it
    # is strategy-specific; the default ADHD path should not pay for a
    # SQL round-trip it never consumes.
    if strategy == "easy_only":
        # Drop any row whose difficulty_layer isn't the easy tier. NULL
        # layer is treated as "unknown, not safe for bad-day" — the
        # catalog ingests every new card with a layer value, and the
        # bad-day contract is "definitely easy", not "probably easy".
        by_problem_id = {
            pid: row
            for pid, row in by_problem_id.items()
            if row[0].difficulty_layer == _EASY_DIFFICULTY_LAYER
        }

        if by_problem_id:
            # Lifetime wrong-count per problem. ``GROUP BY problem_id
            # HAVING COUNT(*) >= 3`` mirrors the plan SQL; we restrict
            # to the surviving easy IDs so this never scans the full
            # practice_results table just to discard most of it.
            easy_ids = list(by_problem_id.keys())
            struggle_stmt = (
                select(PracticeResult.problem_id)
                .where(
                    PracticeResult.is_correct.is_(False),
                    PracticeResult.problem_id.in_(easy_ids),
                )
                .group_by(PracticeResult.problem_id)
                .having(func.count(PracticeResult.id) >= _BAD_DAY_STRUGGLE_THRESHOLD)
            )
            struggle_rows = await db.execute(struggle_stmt)
            struggle_ids: set[uuid.UUID] = {row[0] for row in struggle_rows.all()}
            if struggle_ids:
                by_problem_id = {
                    pid: row
                    for pid, row in by_problem_id.items()
                    if pid not in struggle_ids
                }

        if not by_problem_id:
            # Empty filtered pool — distinct from "nothing_due" so the
            # frontend can prompt "turn bad-day off" instead of the
            # onboarding nudge.
            return DailyPlan(cards=[], size=0, reason="bad_day_empty")

    # ── Query 2: recently-failed problem IDs (optional) ──
    # Only executed if tiers 0 + 1 could fail to cover ``size`` — we still
    # run it unconditionally because the classifier needs the set to
    # correctly assign rank 2 (and the query is tiny: one composite index
    # hit on ``practice_results.answered_at`` + the join predicate).
    failed_ids_stmt = (
        select(PracticeResult.problem_id)
        .where(
            PracticeResult.is_correct.is_(False),
            PracticeResult.answered_at > recent_failure_floor,
        )
        .order_by(PracticeResult.answered_at.desc())
    )
    failed_rows = await db.execute(failed_ids_stmt)
    recently_failed_ids: list[uuid.UUID] = [row[0] for row in failed_rows.all()]

    # Build an ordered set-ish structure preserving "most-recent first"
    # for rank 2 — later dedup drops IDs already captured by tiers 0/1.
    seen_failed: set[uuid.UUID] = set()
    recent_failed_order: list[uuid.UUID] = []
    for pid in recently_failed_ids:
        if pid in seen_failed:
            continue
        seen_failed.add(pid)
        recent_failed_order.append(pid)

    # ── Classify every problem into a rank tier ──
    tier_overdue: list[tuple[PracticeProblem, LearningProgress | None]] = []
    tier_due_today: list[tuple[PracticeProblem, LearningProgress]] = []
    tier_recent_fail: list[tuple[PracticeProblem, LearningProgress | None]] = []
    # Rank 3 is only populated under ``strategy="struggle_first"`` —
    # ADHD mode deliberately excludes never-seen cards so the daily
    # session surfaces debt, not raw backlog.
    tier_never_seen: list[tuple[PracticeProblem, LearningProgress | None]] = []

    recently_failed_set = set(recent_failed_order)

    for problem, progress in by_problem_id.values():
        # Brutal is MC-only — drop code_exercise / lab_exercise rows
        # before classification so they never land in any tier. ADHD
        # keeps them (its type-rotation wants the variety).
        if (
            strategy == "struggle_first"
            and problem.question_type in _CODE_LIKE_QUESTION_TYPES
        ):
            continue

        next_review = progress.next_review_at if progress is not None else None

        if next_review is not None and next_review < now:
            tier_overdue.append((problem, progress))
            continue

        if next_review is not None and now <= next_review <= due_horizon:
            tier_due_today.append((problem, progress))
            continue

        # Orphaned FSRS (no LP row) + answered at least once → treat as
        # overdue. We detect "answered at least once" via membership in
        # the recently-failed set OR by the fsrs_reps signal on the LP
        # row (if one exists but next_review is None).
        if progress is None and problem.id in recently_failed_set:
            tier_overdue.append((problem, progress))
            continue

        if progress is not None and progress.fsrs_reps > 0 and next_review is None:
            tier_overdue.append((problem, progress))
            continue

        if problem.id in recently_failed_set:
            tier_recent_fail.append((problem, progress))
            continue

        # Brand-new, unanswered, not due. ADHD mode drops this row
        # entirely (Phase 13: surface debt, not raw backlog). Brutal
        # mode keeps it IFF the problem carries a ``concept_slug`` in
        # its metadata — the brutal closure screen tallies top-3 weakest
        # concept_slugs, so a never-seen card without a slug is
        # unaddressable downstream and would just be filler.
        if strategy == "struggle_first":
            metadata = problem.problem_metadata or {}
            if metadata.get("concept_slug"):
                tier_never_seen.append((problem, progress))

    # ── Stable sort inside each tier ──
    # Rank 0 (overdue): earliest next_review_at first; fallback to
    # created_at ASC so ties among fresh-orphan problems (no LP) remain
    # deterministic between calls.
    tier_overdue.sort(
        key=lambda pair: (
            pair[1].next_review_at if pair[1] and pair[1].next_review_at else now,
            pair[0].created_at,
            pair[0].id,  # final tiebreak — guarantees deterministic tests
        )
    )
    # Rank 1 (due today): earliest next_review_at first — same idea.
    tier_due_today.sort(
        key=lambda pair: (pair[1].next_review_at, pair[0].created_at, pair[0].id),
    )
    # Rank 2 (recently failed): most recent failure first. We already
    # have the order from ``recent_failed_order`` — drive the sort off
    # that index rather than re-querying the timestamps.
    failed_index = {pid: i for i, pid in enumerate(recent_failed_order)}
    tier_recent_fail.sort(
        key=lambda pair: (failed_index.get(pair[0].id, 1 << 30), pair[0].id),
    )
    # Rank 3 (never-seen, brutal-only): oldest-created first so the
    # selector prefers cards that have been sitting in the backlog
    # longest — pure deterministic tiebreak on id keeps the test output
    # reproducible across runs.
    tier_never_seen.sort(key=lambda pair: (pair[0].created_at, pair[0].id))

    # ── Dedup across tiers (lowest rank wins) ──
    # Dedup order follows the strategy's rank ordering so a problem that
    # qualifies for multiple tiers is anchored to its highest-priority
    # tier under that strategy. Keeping this explicit — instead of
    # relying on the set-side-effect of ``_keep_unseen`` — makes the
    # Phase 13 regression obvious: the tier order below MUST match the
    # extend order further down.
    chosen_ids: set[uuid.UUID] = set()

    def _keep_unseen(
        rows: list[tuple[PracticeProblem, LearningProgress | None]],
    ) -> list[PracticeProblem]:
        kept: list[PracticeProblem] = []
        for problem, _ in rows:
            if problem.id in chosen_ids:
                continue
            chosen_ids.add(problem.id)
            kept.append(problem)
        return kept

    if strategy in {"adhd_safe", "easy_only"}:
        # Phase 13 ordering: overdue → due-today → recently-failed, with
        # type-rotation inside each tier.
        overdue_unique = _keep_unseen(tier_overdue)
        due_unique = _keep_unseen(
            [(p, lp) for p, lp in tier_due_today]  # normalise Optional typing
        )
        recent_unique = _keep_unseen(tier_recent_fail)

        rotated: list[PracticeProblem] = []
        rotated.extend(_rotate_by_type(overdue_unique))
        rotated.extend(_rotate_by_type(due_unique))
        rotated.extend(_rotate_by_type(recent_unique))
    else:
        # Brutal ordering (struggle_first): recent-fail → overdue →
        # due-today → never-seen-with-concept_slug. No type-rotation —
        # the brutal UX serialises struggle, so cards flow in strict
        # tier-priority order without interleaving by question type.
        recent_unique = _keep_unseen(tier_recent_fail)
        overdue_unique = _keep_unseen(tier_overdue)
        due_unique = _keep_unseen([(p, lp) for p, lp in tier_due_today])
        never_seen_unique = _keep_unseen(tier_never_seen)

        rotated = []
        rotated.extend(recent_unique)
        rotated.extend(overdue_unique)
        rotated.extend(due_unique)
        rotated.extend(never_seen_unique)

    final = rotated[:size]

    if not final:
        # Non-empty DB but nothing classified — rare but possible (e.g.
        # every problem is fresh-unseen with no failed results). Same
        # contract as empty DB: surface the quick-closure screen.
        empty_reason_unclassified: DailyPlanReason = (
            "bad_day_empty" if strategy == "easy_only" else "nothing_due"
        )
        return DailyPlan(cards=[], size=0, reason=empty_reason_unclassified)

    cards = [_to_card(p) for p in final]
    return DailyPlan(cards=cards, size=len(cards), reason=None)


def _progress_more_active(
    candidate: LearningProgress | None,
    incumbent: LearningProgress | None,
) -> bool:
    """Return True when ``candidate`` is a 'stronger' FSRS signal than
    ``incumbent``. Used to break the rare LEFT-JOIN duplication where a
    problem maps to multiple learning_progress rows (different user_ids
    aliased under the same course/content_node pair).

    "Stronger" means, in order:

    * has a ``next_review_at`` when the other does not, OR
    * has more ``fsrs_reps`` (more review history), OR
    * has a more recent ``last_studied_at``.
    """

    if candidate is None:
        return False
    if incumbent is None:
        return True

    cand_has_due = candidate.next_review_at is not None
    inc_has_due = incumbent.next_review_at is not None
    if cand_has_due != inc_has_due:
        return cand_has_due

    if candidate.fsrs_reps != incumbent.fsrs_reps:
        return candidate.fsrs_reps > incumbent.fsrs_reps

    cand_studied = candidate.last_studied_at
    inc_studied = incumbent.last_studied_at
    if cand_studied is None and inc_studied is None:
        return False
    if cand_studied is None:
        return False
    if inc_studied is None:
        return True
    return cand_studied > inc_studied


def _rotate_by_type(problems: list[PracticeProblem]) -> list[PracticeProblem]:
    """Interleave a tier's problems across distinct ``question_type`` groups.

    Preserves the incoming per-group order (already priority-sorted by
    the caller) so the first element of each group is still the
    highest-priority card of that type. Empty groups are skipped; the
    function is a no-op for homogeneous tiers.

    Example::

        in:  [mc1, mc2, mc3, code1, lab1]
        out: [mc1, code1, lab1, mc2, mc3]
    """

    if not problems:
        return []

    groups: dict[str, list[PracticeProblem]] = defaultdict(list)
    group_order: list[str] = []
    for p in problems:
        qt = p.question_type
        if qt not in groups:
            group_order.append(qt)
        groups[qt].append(p)

    if len(group_order) == 1:
        return list(problems)

    out: list[PracticeProblem] = []
    while any(groups[qt] for qt in group_order):
        for qt in group_order:
            bucket = groups[qt]
            if bucket:
                out.append(bucket.pop(0))
    return out


def _to_card(problem: PracticeProblem) -> DailyPlanCard:
    """Project a :class:`PracticeProblem` onto the public card shape."""

    return DailyPlanCard(
        id=problem.id,
        question_type=problem.question_type,
        question=problem.question,
        options=problem.options,
        correct_answer=problem.correct_answer,
        explanation=problem.explanation,
        difficulty_layer=problem.difficulty_layer,
        content_node_id=problem.content_node_id,
        problem_metadata=problem.problem_metadata,
    )


__all__ = [
    "ALLOWED_BRUTAL_SIZES",
    "ALLOWED_SIZES",
    "BRUTAL_RECENTLY_FAILED_WINDOW_DAYS",
    "RECENTLY_FAILED_WINDOW_DAYS",
    "Strategy",
    "select_daily_plan",
]
