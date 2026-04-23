"""Pydantic schemas for the ADHD daily-session endpoint (Phase 13 T1+T2).

Contracts consumed by ``routers.sessions`` and produced by
``services.daily_plan.select_daily_plan``.

The daily-session feature is anchored in MASTER §8 ADHD UX: pick a tiny,
guilt-free batch of 1 / 5 / 10 cards prioritised by FSRS overdue → due
today → recently-failed. The response shape deliberately stays close to
the existing :class:`models.practice.PracticeProblem` row so the frontend
can reuse the same card renderer used by quiz and flashcard flows.

Design notes
------------
* **Session size is a closed enum.** The endpoint only accepts 1 / 5 / 10;
  other integers are rejected with HTTP 422 (pydantic ``Literal`` handles
  this automatically when bound to a FastAPI ``Query``). The UX argument
  for the fixed trio lives in ``plan/adhd_ux_phase13.md`` §Q2: every ADHD
  user's first session is either "one card now" or "five cards, done".
  Letting the caller pass ``size=7`` opens the door to dashboards asking
  for 50 cards, which is exactly the anti-pattern we're avoiding.

* **``reason`` is a three-branch signal, not a status enum.**
  ``reason == "nothing_due"`` means the pool was genuinely empty (no FSRS
  card past due, no recently-failed row). ``reason is None`` covers both
  "we filled the batch" and "we returned fewer than ``size`` because the
  pool is small but non-empty" — the frontend renders the truncated list
  in the second case. A full enum would encode states the UI does not
  actually need to distinguish.

* **Card shape is a subset of ``PracticeProblem``.** We expose the public
  fields the renderer needs (``question``, ``options``, ``correct_answer``,
  ``explanation``, ``problem_metadata``, ``difficulty_layer``,
  ``content_node_id``) and keep ``question_type`` so the client can pick
  the right interactive widget. Internal bookkeeping columns (``source``,
  ``source_owner``, ``locked``, etc.) are deliberately omitted — this is
  the ADHD "just show me the card" contract, not the curriculum editor.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


DailySessionSize = Literal[1, 5, 10]
"""Allowed values for the ``size`` query parameter. Any other integer is
rejected with HTTP 422 by FastAPI's ``Literal`` validator — see §Q2 in
``plan/adhd_ux_phase13.md`` for why we hard-code the trio."""


BrutalSessionSize = Literal[20, 30, 50]
"""Allowed values for the ``size`` query parameter on the Brutal Drill
endpoint. Phase 6 explicitly targets interview-prep users who want a
deliberately heavy session — the trio mirrors the struggle-first budget
defined in ``plan/brutal_drill_mode_phase6.md``. Any other integer is
rejected with HTTP 422 via the same ``Literal`` mechanism the daily
endpoint uses."""


BrutalTimeoutSeconds = Literal[15, 30, 60]
"""Per-card timeout values surfaced to the Brutal frontend. Kept next to
:data:`BrutalSessionSize` because both live behind the same feature flag
and move together in the UX spec (§F6 of the phase 6 plan)."""


class DailyPlanCard(BaseModel):
    """One card in the daily-plan response.

    Fields mirror the publicly-renderable columns of
    :class:`models.practice.PracticeProblem`. ``problem_metadata`` is
    passed through verbatim so code-exercise and lab-exercise rows keep
    their runner-specific payload (starter_code, target_url, etc.) — the
    same way :class:`schemas.curriculum.CardCandidate` flows through
    ``save-candidates``.
    """

    id: uuid.UUID
    question_type: str
    question: str
    options: dict[str, Any] | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    difficulty_layer: int | None = None
    content_node_id: uuid.UUID | None = None
    problem_metadata: dict[str, Any] | None = None


class DailyPlan(BaseModel):
    """Response body for ``GET /api/sessions/daily-plan``.

    Fields:
        cards: The curated batch, ordered by priority (overdue →
            due-today → recently-failed), with type-rotation applied
            inside each priority tier. At most ``requested_size`` entries.
        size: ``len(cards)``. Never larger than the requested size;
            smaller when the pool is partially filled.
        reason: ``None`` in the happy path (including partial fills).
            ``"nothing_due"`` when the pool is empty — the UI uses this
            to render the quick-closure screen instead of a blank list.
    """

    cards: list[DailyPlanCard] = Field(default_factory=list)
    size: int = Field(ge=0)
    reason: str | None = None


class BrutalPlanResponse(BaseModel):
    """Response body for ``GET /api/sessions/brutal-plan`` (Phase 6).

    Mirrors :class:`DailyPlan` but narrows the contract in two ways:

    * ``strategy`` is pinned to ``"struggle_first"`` — the only selector
      the Brutal endpoint exposes. A field rather than a silent default
      so the frontend can surface the mode in UI copy without a second
      round-trip.
    * ``warning`` is an explicit ``"pool_small"`` signal when the pool
      could not fill the requested size. The daily endpoint squashes
      that case into ``reason=None`` because an ADHD session happily
      accepts a partial fill; Brutal users asked for a heavy batch on
      purpose, so the frontend raises a toast instead of silently
      shrinking the deck.

    ``cards`` reuses :class:`DailyPlanCard` so the frontend card renderer
    stays shared between daily and brutal sessions. The MC-only filter
    and tier-rank inversion are applied in the service — consumers of
    this schema never see code-exercise / lab-exercise rows.
    """

    cards: list[DailyPlanCard] = Field(default_factory=list)
    size: int = Field(ge=0)
    strategy: Literal["struggle_first"] = "struggle_first"
    warning: Literal["pool_small"] | None = None


__all__ = [
    "BrutalPlanResponse",
    "BrutalSessionSize",
    "BrutalTimeoutSeconds",
    "DailyPlan",
    "DailyPlanCard",
    "DailySessionSize",
]
