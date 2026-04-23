"""Curriculum endpoints for §14.5 v2.1 (URL → auto-curriculum).

Task T3 ships the first route: ``GET /api/courses/{course_id}/roadmap``.

It reads the roadmap path that T2's ``persist_syllabus`` writes into
``courses.metadata_['roadmap']`` (a list of ``KnowledgeNode`` IDs in
learner-recommended study order), joins each node with the current user's
``ConceptMastery`` row, and returns an ordered list of :class:`RoadmapEntry`.

Design notes
------------
* **Path order wins, DB order is ignored.** We resolve nodes with ``IN (...)``
  and then reorder in Python using the path list, so a missing/deleted node
  is silently skipped rather than causing a 500. A SQL ``CASE WHEN`` sort
  would also work but Python reordering keeps the query simple and the
  deleted-node branch trivially covered.
* **LEFT JOIN on ConceptMastery** — fresh courses have no mastery rows yet;
  we fall back to ``0.0`` rather than dropping the node.
* **user_id resolution** matches every other router in the repo: via
  ``Depends(get_current_user)``, which transparently handles single-user
  mode (``AUTH_ENABLED=false``) by returning/creating the one local user.
* **404** is raised by ``get_course_or_404`` (``NotFoundError`` → the global
  ``AppError`` handler in ``main.py`` turns that into HTTP 404); this
  distinguishes "course doesn't exist" from "course has no syllabus yet"
  (the latter returns ``[]``).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.generated_asset import GeneratedAsset
from models.knowledge_graph import ConceptMastery, KnowledgeNode
from models.practice import PracticeProblem
from models.user import User
from schemas.curriculum import (
    CardCandidatesResponse,
    RoadmapEntry,
    SaveCandidatesRequest,
    SaveCandidatesResponse,
)
from services.agent import card_cache
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{course_id}/roadmap",
    response_model=list[RoadmapEntry],
    summary="Get course roadmap",
    description=(
        "Return the ordered study-path of topic nodes for a course, with "
        "per-user mastery scores. Order matches "
        "``course.metadata_['roadmap']['path']`` as written by the syllabus "
        "builder. Returns an empty list if the course has no syllabus yet."
    ),
)
async def get_course_roadmap(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoadmapEntry]:
    """Return the roadmap entries for ``course_id`` in syllabus-path order.

    Flow:
        1. Resolve the course (404 if it doesn't exist or is not owned by
           the current user).
        2. Read ``course.metadata_['roadmap']['path']`` — a list of
           ``KnowledgeNode`` ID strings. Empty/missing → return ``[]``.
        3. Fetch the referenced nodes joined with the current user's
           ``ConceptMastery`` (LEFT JOIN — no row yet → mastery 0.0).
        4. Re-assemble in path order, skipping nodes that no longer exist.
    """

    course = await get_course_or_404(db, course_id, user_id=user.id)

    metadata = course.metadata_ or {}
    roadmap_meta = metadata.get("roadmap") or {}
    raw_path: list[str] = list(roadmap_meta.get("path") or [])
    if not raw_path:
        return []

    # Parse path entries into UUIDs while preserving the original path
    # index. Malformed strings (stale / corrupt metadata) yield ``None`` so
    # the surviving entries keep their *original* positions — same policy
    # as deleted nodes below. We never 500 on a bad blob.
    path_entries: list[tuple[int, uuid.UUID | None]] = []
    for idx, raw in enumerate(raw_path):
        try:
            path_entries.append((idx, uuid.UUID(str(raw))))
        except (ValueError, TypeError):
            logger.warning(
                "roadmap: course %s has a non-UUID path entry %r at index %d; skipping",
                course_id,
                raw,
                idx,
            )
            path_entries.append((idx, None))

    valid_ids = [node_id for _, node_id in path_entries if node_id is not None]
    if not valid_ids:
        return []

    # One round-trip: all nodes on the path scoped to this course, with a
    # LEFT JOIN against ConceptMastery for *this user* so missing mastery
    # rows materialise as NULL → 0.0 below.
    stmt = (
        select(KnowledgeNode, ConceptMastery)
        .outerjoin(
            ConceptMastery,
            (ConceptMastery.knowledge_node_id == KnowledgeNode.id)
            & (ConceptMastery.user_id == user.id),
        )
        .where(
            KnowledgeNode.course_id == course_id,
            KnowledgeNode.id.in_(valid_ids),
        )
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Build lookup: the LEFT JOIN yields (KnowledgeNode, ConceptMastery|None).
    by_node_id: dict[uuid.UUID, tuple[KnowledgeNode, ConceptMastery | None]] = {
        node.id: (node, mastery) for node, mastery in rows
    }

    entries: list[RoadmapEntry] = []
    for position, node_id in path_entries:
        if node_id is None:
            continue  # malformed path entry, already logged above
        pair = by_node_id.get(node_id)
        if pair is None:
            # Node referenced by the roadmap path has been deleted since the
            # syllabus was generated. Skip it — don't 500, don't emit a
            # ghost entry. Surviving entries keep their original positions.
            logger.info(
                "roadmap: course %s path references missing node %s; skipping",
                course_id,
                node_id,
            )
            continue
        node, mastery = pair
        node_metadata = node.metadata_ or {}
        slug = str(node_metadata.get("slug") or "")
        mastery_score = float(mastery.mastery_score) if mastery is not None else 0.0
        entries.append(
            RoadmapEntry(
                node_id=node.id,
                slug=slug,
                topic=node.name,
                blurb=node.description,
                mastery_score=mastery_score,
                position=position,
            )
        )

    return entries


@router.get(
    "/sessions/{session_id}/messages/{message_id}/card-candidates",
    response_model=CardCandidatesResponse,
    summary="Fetch flashcard candidates for a completed tutor turn",
    description=(
        "Polling endpoint paired with the SSE ``pending_cards`` event "
        "emitted by the chat orchestrator after each teaching-style "
        "turn. Waits up to 10 seconds for the background "
        "``extract_card_candidates`` task to finish, OR returns the "
        "cached result immediately if it is already done, OR returns "
        "``{cards:[], reason:'no_candidates'}`` when no task is pending "
        "for this message. Always 200, never 404."
    ),
)
async def get_card_candidates(
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> CardCandidatesResponse:
    """Return cached card candidates for ``(session_id, message_id)``.

    Behaviour:
        * Task completed → ``cards`` contains 0-3 candidates.
        * Task in-flight → waits up to 10s for completion, then returns
          the result.
        * No task pending for this key → ``cards=[]``, ``reason=
          "no_candidates"``.

    The endpoint deliberately does NOT 404 on missing keys: the
    orchestrator only emits ``pending_cards`` for teaching-style turns,
    so a miss here means "this turn didn't trigger card extraction" —
    a valid, expected state for the frontend to render as "no toast".

    Note on auth: the underlying cache is keyed by ``session_id`` which
    is generated per chat session server-side. We still require
    ``get_current_user`` so the route isn't unauthenticated, but the
    per-session enforcement that a poller is the same user who ran the
    turn is TODO — a good followup if this endpoint ever exposes user
    data beyond generic flashcard prompts. For §14.5 v2.1 this is
    considered acceptable.
    """

    _ = user  # dependency kept for auth gate + audit symmetry with roadmap
    cards = await card_cache.await_or_get(session_id, message_id, timeout_s=10.0)
    if cards is None:
        return CardCandidatesResponse(cards=[], reason="no_candidates")
    return CardCandidatesResponse(cards=cards)


@router.post(
    "/{course_id}/flashcards/save-candidates",
    response_model=SaveCandidatesResponse,
    summary="Save chat-spawned flashcard candidates",
    description=(
        "Path B dual-write persistence for §14.5 T6. Each saved "
        "candidate lands in BOTH ``practice_problems`` (canonical "
        "quiz-engine row) AND ``generated_assets`` with "
        "``asset_type='flashcards'`` (one row holding N cards with "
        "inline FSRS state) so the card shows up immediately in "
        "``GET /api/flashcards/due/{course_id}``. Cross-linked via "
        "``practice_problems.problem_metadata['asset_id']`` and "
        "``generated_assets.content['cards'][i]['practice_problem_id']`` "
        "for later analytics."
    ),
)
async def save_flashcard_candidates(
    course_id: uuid.UUID,
    body: SaveCandidatesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SaveCandidatesResponse:
    """Dual-write N cards to ``practice_problems`` + 1 ``generated_assets`` row.

    Flow:
        1. 404 via ``get_course_or_404`` if the course isn't owned by
           the current user.
        2. Reject empty batch with HTTP 400 — the pydantic schema already
           enforces ``min_length=1`` but we surface the error message
           explicitly for the rare direct-python test path.
        3. Resolve each candidate's ``concept_slug`` to a
           ``KnowledgeNode`` in THIS course. Unmatched slugs → the
           corresponding ``PracticeProblem.content_node_id`` stays
           ``NULL`` and a warning is appended to the response.
        4. Pre-generate the asset UUID so each ``PracticeProblem`` can
           cross-link it in ``problem_metadata['asset_id']``.
        5. Insert N ``PracticeProblem`` rows, flush to materialise their
           IDs, then insert one ``GeneratedAsset`` row whose
           ``content['cards'][i]['practice_problem_id']`` points back at
           the matching problem. Commit once — if any insert raises, we
           rollback so the two persistence paths can never drift.

    The ``fsrs`` dict inline default matches
    ``services.spaced_repetition.flashcards.generate_flashcards`` exactly
    (``state='new'``, ``due=None``) so ``GET /api/flashcards/due/{id}``
    classifies each new card as due (see ``flashcards.py:303-308``: cards
    with no FSRS data — or with ``due=None`` — are always returned).
    """

    # 1. Ownership gate (404 if missing / not owned).
    await get_course_or_404(db, course_id, user_id=user.id)

    # 2. Empty-batch guard. Pydantic enforces min_length=1 but we also
    # surface a domain-level 400 for callers that bypass validation.
    if not body.candidates:
        raise HTTPException(status_code=400, detail="No candidates to save")

    # 3. Resolve concept_slug → KnowledgeNode.id, scoped to this course.
    # CompatJSONB metadata_ holds ``{"slug": "...", "source": "..."}``; we
    # match inside the JSON blob via SQLAlchemy's JSON accessor. Rows
    # without a slug are skipped here (they stay content_node_id=NULL).
    requested_slugs = {c.concept_slug for c in body.candidates if c.concept_slug}
    slug_to_node_id: dict[str, uuid.UUID] = {}
    # Phase 4 T6: screenshot origin flips an ``ungrounded`` flag per card
    # whenever the candidate's slug (or lack thereof) doesn't resolve to a
    # real KnowledgeNode in this course. We always load the course's nodes
    # for screenshot batches so the resolver sees every slug, even ones
    # that aren't in ``requested_slugs`` (None-slug cards).
    if requested_slugs or body.spawn_origin == "screenshot":
        stmt = select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
        result = await db.execute(stmt)
        for node in result.scalars().all():
            node_meta = node.metadata_ or {}
            node_slug = node_meta.get("slug")
            if node_slug and node_slug in requested_slugs:
                slug_to_node_id[node_slug] = node.id

    warnings: list[str] = []
    for c in body.candidates:
        if c.concept_slug and c.concept_slug not in slug_to_node_id:
            warnings.append(
                f"concept_slug {c.concept_slug!r} did not match any "
                f"knowledge node in course {course_id}"
            )

    # 4. Pre-generate the asset UUID so PracticeProblem rows can
    # cross-link it in their problem_metadata.
    asset_uuid = uuid.uuid4()

    # 5. Dual-write, atomic on error via rollback.
    pp_rows: list[PracticeProblem] = []
    try:
        for c in body.candidates:
            # spawn_origin propagates from the request body (default
            # "chat_turn" for §14.5 compatibility; "screenshot" for
            # Phase 4 screenshot-to-drill flow).
            problem_metadata: dict[str, object] = {
                "spawn_origin": body.spawn_origin,
                "concept_slug": c.concept_slug,
                "asset_id": str(asset_uuid),
            }
            # Only record screenshot_hash when the candidate actually
            # carries one — keeps chat-turn rows' metadata unchanged.
            if c.screenshot_hash is not None:
                problem_metadata["screenshot_hash"] = c.screenshot_hash

            # Phase 4 T6: ungrounded = the card's concept_slug didn't
            # resolve to a real KnowledgeNode in this course. Only added
            # for screenshot-origin batches — chat-turn cards keep the
            # original metadata shape (backward-compat with §14.5 tests).
            # A missing slug is treated as ungrounded by construction.
            if body.spawn_origin == "screenshot":
                problem_metadata["ungrounded"] = (
                    c.concept_slug is None or c.concept_slug not in slug_to_node_id
                )

            pp = PracticeProblem(
                course_id=course_id,
                content_node_id=slug_to_node_id.get(c.concept_slug)
                if c.concept_slug
                else None,
                question_type="flashcard",
                question=c.front,
                correct_answer=c.back,
                source="ai_generated",
                problem_metadata=problem_metadata,
            )
            db.add(pp)
            pp_rows.append(pp)

        # Flush once to populate PracticeProblem.id so we can cross-link
        # back from the GeneratedAsset card payload.
        await db.flush()

        # Build the inline card dicts. Keys mirror what
        # services.spaced_repetition.flashcards.generate_flashcards
        # writes (flashcards.py:105-115) so LECTOR / review /
        # due-list code paths see a consistent shape.
        cards_content = []
        for c, pp in zip(body.candidates, pp_rows):
            cards_content.append(
                {
                    "id": str(uuid.uuid4()),
                    "front": c.front,
                    "back": c.back,
                    "course_id": str(course_id),
                    "concept_slug": c.concept_slug,
                    "practice_problem_id": str(pp.id),
                    "fsrs": {
                        "difficulty": 5.0,
                        "stability": 0.0,
                        "reps": 0,
                        "lapses": 0,
                        "state": "new",
                        "due": None,
                    },
                }
            )

        asset = GeneratedAsset(
            id=asset_uuid,
            user_id=user.id,
            course_id=course_id,
            asset_type="flashcards",  # PLURAL — matches /due filter
            title=f"Chat-spawned cards ({len(body.candidates)})",
            content={
                "cards": cards_content,
                "metadata": {
                    "source": "ai_generated",
                    "spawn_origin": body.spawn_origin,
                },
            },
            metadata_={
                "count": len(body.candidates),
                "source": "ai_generated",
                "spawn_origin": body.spawn_origin,
            },
        )
        db.add(asset)
        await db.flush()
        await db.commit()
    except Exception:
        # Any failure rolls back so we never leave cards in just one of
        # the two persistence paths.
        await db.rollback()
        raise

    return SaveCandidatesResponse(
        saved_problem_ids=[pp.id for pp in pp_rows],
        asset_id=asset_uuid,
        count=len(pp_rows),
        warnings=warnings,
    )


__all__ = ["router"]
