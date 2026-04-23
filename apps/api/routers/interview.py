"""Interviewer Agent HTTP surface — Phase 5 T4.

Five endpoints drive the mock-interview loop:

* ``POST /interview/start`` — corpus-empty gate + rate limit + create session + first Q.
* ``POST /interview/{id}/answer`` — SSE stream: grade → next-question | completed.
* ``GET  /interview/{id}`` — rehydrate full state for pause/resume.
* ``POST /interview/{id}/abandon`` — mark ``completed_early`` + inline summary.
* ``POST /interview/{id}/save-gaps`` — spawn flashcards via §14.5 reuse.

Notes for the reader:

* The router consciously does NOT put the :class:`InterviewerAgent` into
  ``AGENT_REGISTRY``. The chat orchestrator never routes to it; the
  interview loop is its own UX surface.
* Rate limit is an **in-memory token bucket keyed by user_id**, 5 sessions
  per 24 h, mirroring the pattern in ``upload_screenshot.py``. Perfectly
  adequate for a personal-tool single-process deployment; swap for Redis
  if/when the thing ever runs on multiple workers.
* The corpus-empty gate for ``behavioral|mixed`` modes reads
  ``content/star_stories.md`` and uses ``_todo_density`` from T2 to count
  stories whose Action + Result sections are < 50% TODO placeholders.
  When the learner hasn't filled in at least two, we return HTTP 400 with
  a ``cta_url`` so the frontend can deep-link back to the content file.
* The SSE generator for ``/answer`` uses ``sse_starlette``'s
  :class:`EventSourceResponse` — same mechanism as ``chat.py``. Events
  are ``rubric`` → (``next_question`` | ``completed``).
* The save-gaps endpoint calls ``save_flashcard_candidates`` **in-process**
  (not via HTTP). T5 will extend the ``spawn_origin`` Literal to accept
  ``"interview"``; until then we pass ``"chat_turn"`` with a TODO so the
  feature unblocks and the audit-trail field flips the moment T5 lands.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database import async_session, get_db
from models.interview import InterviewSession, InterviewTurn
from models.user import User
from routers.curriculum import save_flashcard_candidates
from schemas.curriculum import CardCandidate, SaveCandidatesRequest
from schemas.interview import (
    AbandonResponse,
    InterviewAnswerRequest,
    InterviewSessionStateResponse,
    InterviewStartRequest,
    InterviewStartResponse,
    RubricScores,
    SaveGapsRequest,
    SaveGapsResponse,
    SummaryResponse,
    TurnResponse,
)
from services.agent.agents.interviewer import InterviewerAgent
from services.agent.agents.interviewer_prompts import CONTENT_DIR
from services.agent.state import AgentContext
from services.auth.dependency import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Tunables ────────────────────────────────────────────────────────

# Turns-per-duration mapping. Anything outside this dict is rejected by
# the Pydantic Literal on ``InterviewStartRequest.duration``, so there's
# no default branch to guard here.
_TURNS_BY_DURATION: dict[str, int] = {"quick": 3, "standard": 10, "deep": 15}

# Round-robin question-type pattern used when ``mode="mixed"``. Per the
# plan §Architect, 40/40/20 behavioral/technical/code_defense is the
# target blend, so a 5-element pattern is the minimum that can hit it
# exactly. For non-mixed modes we ignore this and use the mode itself.
_MIXED_PATTERN: tuple[str, ...] = (
    "behavioral",
    "technical",
    "behavioral",
    "technical",
    "code_defense",
)

# Rate limit — 5 interview starts per user per 24h. The bucket is an
# in-process deque of timestamps per user_id; on each ``/start`` we evict
# entries older than 24h and reject (HTTP 429) when the deque would
# exceed 5. Not Redis — personal-tool single-process scope.
_RATE_LIMIT_PER_DAY: int = 5
_RATE_LIMIT_WINDOW_SEC: float = 24 * 60 * 60  # 86_400

# Corpus-empty gate — the learner must have filled at least this many
# STAR stories before starting a behavioral/mixed session. "Filled"
# means Action + Result sections for that story have <50% TODO-density.
_MIN_FILLED_STORIES: int = 2
_TODO_DENSITY_THRESHOLD: float = 0.5
# A story needs this many real (non-TODO, non-scaffolding) words in its
# Action+Result combined before the TODO-density ratio is trusted. Shell
# stories (just ``**A:**`` + ``_TODO_`` bullets) never clear this floor.
_MIN_REAL_WORDS: int = 20

# File inside ``content/`` we scan for the corpus-empty gate. Kept here
# (not hard-coded against ``_STAR_FILE`` in prompts) so the gate survives
# the prompts module restructuring if that ever happens.
_STAR_FILENAME: str = "star_stories.md"


# ── Module-level state ──────────────────────────────────────────────

# Per-user deque of rate-limit timestamps. Populated lazily.
_RATE_LIMIT_STATE: dict[str, deque[float]] = defaultdict(deque)

# Sentinel prompt-injection defence: tests monkeypatch these names on this
# module rather than the service module, matching the upload_screenshot
# convention (tests patch the router-module binding, not the import source).
_InterviewerAgent = InterviewerAgent
_save_flashcard_candidates = save_flashcard_candidates


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_user_id(user: User) -> str:
    """Normalise the rate-limit key across auth modes.

    Mirrors ``upload_screenshot._resolve_user_id`` so the two routers
    share one mental model of "this is the rate-limit key".
    """

    if user is None or user.id is None:
        return "default"
    return str(user.id)


def _check_rate_limit(user_id: str) -> None:
    """Raise HTTP 429 when ``user_id`` exceeds 5 interview starts / 24h.

    Uses ``time.monotonic`` so tests can monkeypatch a fake clock without
    waiting an actual 24 hours. Evicts expired entries on every call so
    the bucket slides naturally.
    """

    now = time.monotonic()
    bucket = _RATE_LIMIT_STATE[user_id]

    while bucket and bucket[0] <= now - _RATE_LIMIT_WINDOW_SEC:
        bucket.popleft()

    if len(bucket) >= _RATE_LIMIT_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="Slow down — 5 interview sessions per day",
        )

    bucket.append(now)


# ── Corpus-empty gate ───────────────────────────────────────────────

# Match either ``## Story N`` (level 2) headings — the star_stories.md
# structure from Phase 5 content. We scan per-story because the gate
# needs to count stories whose Action + Result are filled, not whether
# the file as a whole is filled.
_STORY_HEADING_RE = re.compile(r"^##\s+Story\s+\d+", re.MULTILINE)
_TODO_TOKEN_RE = re.compile(r"_TODO[_:]?", re.IGNORECASE)


def _split_stories(md_text: str) -> list[str]:
    """Return a list of per-story markdown blocks.

    Uses ``re.split`` with the same ``## Story N`` regex so the returned
    blocks each include their own heading; blocks before the first
    heading (file preamble) are dropped.
    """

    matches = list(_STORY_HEADING_RE.finditer(md_text))
    if not matches:
        return []
    blocks: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        blocks.append(md_text[start:end])
    return blocks


def _extract_action_result(block: str) -> str:
    """Return the Action + Result portion of one story block.

    Heuristic match on the plan-standard headings
    (``**A (Action):**``, ``**A:**``, ``**R (Result):**``, ``**R:**``)
    so the gate works on both the long-form and shorthand variants
    used across the corpus. If no Action/Result headings are found we
    return the whole block — treating that as "the story exists but
    its shape is off" still lets ``_todo_density`` do the right thing
    (TODO-heavy free text → ungated, clean free text → gated open).
    """

    # Look for the first Action heading and slurp until EOF of the block.
    action_pat = re.compile(r"\*\*A(?:\s*\(Action\))?:\*\*", re.IGNORECASE)
    m = action_pat.search(block)
    if m is None:
        return block
    return block[m.start() :]


def _count_filled_stories(md_text: str) -> int:
    """Return number of stories whose Action+Result are genuinely filled.

    Heuristic (from the task spec — "TODO-density < 0.5 in Action/Result"):
      * Strip the Action+Result excerpt of ``_TODO`` markers + markdown
        structural tokens (``>``, ``*``, ``-``, headings).
      * A story counts as filled iff:
        1. the cleaned excerpt has ≥ ``_MIN_REAL_WORDS`` real content words,
           AND
        2. the fraction ``todo_count / (todo_count + real_words)`` is below
           ``_TODO_DENSITY_THRESHOLD`` (TODO markers do NOT dominate).

    Rationale: a raw word-ratio heuristic misfires on TODO-heavy stories
    that still have a lot of markdown scaffolding around the TODO markers
    (bullet prefixes ``-``, quote prefixes ``>``), which dilute the TODO
    count. Strip the scaffolding first, then compare. Empty/shell stories
    (all ``_TODO`` or just heading) never clear the word floor, so they
    always count as 0 filled.
    """

    filled = 0
    for block in _split_stories(md_text):
        excerpt = _extract_action_result(block)
        if not excerpt.strip():
            continue

        todo_count = len(_TODO_TOKEN_RE.findall(excerpt))
        # Remove TODO markers so the "real words" count is accurate.
        cleaned = _TODO_TOKEN_RE.sub(" ", excerpt)

        real_words = 0
        for tok in cleaned.split():
            # Drop pure markdown syntax + very-short scaffolding tokens.
            stripped = tok.strip("*_`>-:#")
            if len(stripped) < 2:
                continue
            real_words += 1

        if real_words < _MIN_REAL_WORDS:
            continue

        denom = todo_count + real_words
        density = todo_count / denom if denom else 1.0
        if density < _TODO_DENSITY_THRESHOLD:
            filled += 1
    return filled


def _corpus_empty_gate(mode: str) -> None:
    """Raise HTTP 400 when the behavioral corpus is too thin to ground on.

    Only triggers for ``mode in {"behavioral", "mixed"}`` — technical and
    code_defense interviews lean on ``code_defense_drill.md`` which is
    covered by T3's in-agent ``grounding_source="generic"`` fallback.
    """

    if mode not in {"behavioral", "mixed"}:
        return

    star_path: Path = CONTENT_DIR / _STAR_FILENAME
    try:
        md_text = star_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        md_text = ""

    filled = _count_filled_stories(md_text)
    if filled < _MIN_FILLED_STORIES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "content_empty",
                "detail": (
                    f"Fill at least {_MIN_FILLED_STORIES} STAR stories "
                    "before behavioral interviews "
                    f"(found {filled} filled)."
                ),
                "cta_url": "/content/star_stories.md",
            },
        )


# ── Mode / question-type routing ────────────────────────────────────


def _question_type_for_turn(mode: str, turn_number: int) -> str:
    """Pick the ``question_type`` for the next turn.

    For single-mode sessions we reuse the mode itself. For ``mixed`` we
    round-robin the ``_MIXED_PATTERN`` tuple so turn 1 is behavioral,
    turn 2 technical, etc. ``turn_number`` is 1-indexed.
    """

    if mode == "mixed":
        return _MIXED_PATTERN[(turn_number - 1) % len(_MIXED_PATTERN)]
    return mode


# ── Serialisation helpers ───────────────────────────────────────────


def _turn_to_response(turn: InterviewTurn) -> TurnResponse:
    """Convert an ``InterviewTurn`` ORM row to the wire schema.

    ``rubric_scores_json`` is stored as the raw LLM-produced dict; we
    defensively ``model_validate`` it so a historically-malformed row
    can't crash a rehydrate call — we just drop the rubric and keep
    the turn.
    """

    rubric: RubricScores | None = None
    raw = turn.rubric_scores_json
    if isinstance(raw, dict):
        try:
            rubric = RubricScores.model_validate(raw)
        except ValueError:
            logger.warning(
                "interview_rubric_validate_fail turn=%s",
                turn.id,
            )
            rubric = None

    return TurnResponse(
        turn_number=turn.turn_number,
        question=turn.question,
        question_type=turn.question_type,
        grounding_source=turn.grounding_source,
        answer=turn.answer,
        rubric=rubric,
        answer_time_ms=turn.answer_time_ms,
    )


def _attach_worst_turn_id(
    summary: SummaryResponse, turns: list[InterviewTurn]
) -> SummaryResponse:
    """Populate ``summary.worst_turn_id`` from the DB turns.

    ``InterviewerAgent.write_summary_inline`` returns ``worst_turn_id=None``
    because its inputs (``TurnResponse``) lack the DB UUID. The router
    knows the UUIDs, so here we map the lowest-averaged turn back to its
    ``InterviewTurn.id`` and stamp the response.
    """

    graded = [t for t in turns if isinstance(t.rubric_scores_json, dict)]
    if not graded:
        return summary

    def _turn_avg(turn: InterviewTurn) -> float:
        scores_raw = turn.rubric_scores_json or {}
        dims = scores_raw.get("dimensions") or {}
        values: list[float] = []
        for dim in dims.values():
            if isinstance(dim, dict):
                s = dim.get("score")
                if isinstance(s, int | float):
                    values.append(float(s))
        if not values:
            return 6.0  # treat unparseable as "not worst"
        return sum(values) / len(values)

    worst = min(graded, key=_turn_avg)
    return summary.model_copy(update={"worst_turn_id": worst.id})


# ── Endpoint 1: POST /interview/start ───────────────────────────────


@router.post(
    "/interview/start",
    response_model=InterviewStartResponse,
    summary="Start a new interview session",
    description=(
        "Creates an ``InterviewSession`` + first ``InterviewTurn``. "
        "Rejected with HTTP 400 when ``mode`` needs a behavioral corpus "
        "and the learner hasn't filled ≥2 STAR stories; with HTTP 429 "
        "when the learner exceeds 5 interview starts per 24h."
    ),
)
async def start_interview(
    body: InterviewStartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewStartResponse:
    """Start flow — see module docstring for the ordered steps."""

    # 1. Rate-limit check (before any DB / LLM cost).
    user_id = _resolve_user_id(user)
    _check_rate_limit(user_id)

    # 2. Corpus-empty gate for behavioral / mixed modes.
    _corpus_empty_gate(body.mode)

    # 3. Total turns from duration.
    total_turns = _TURNS_BY_DURATION[body.duration]

    # 4. Persist the session row so the agent call site has a stable ID.
    session = InterviewSession(
        user_id=user.id,
        course_id=body.course_id,
        mode=body.mode,
        duration=body.duration,
        project_focus=body.project_focus,
        total_turns=total_turns,
        completed_turns=0,
        status="in_progress",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # 5. Generate the first question. ``InterviewerAgent.generate_question``
    # never raises — it falls back to a generic question on any LLM/parse
    # failure so we can always advance turn 1.
    question_type = _question_type_for_turn(body.mode, 1)
    agent = _InterviewerAgent()
    ctx = AgentContext(
        user_id=user.id,
        course_id=body.course_id or uuid.uuid4(),
    )
    result = await agent.generate_question(
        ctx,
        turn_number=1,
        total_turns=total_turns,
        project_focus=body.project_focus,
        mode=body.mode,
        question_type=question_type,
        prev_questions=[],
    )

    # 6. Persist the first turn.
    first_turn = InterviewTurn(
        session_id=session.id,
        turn_number=1,
        question_type=str(result.get("question_type") or question_type),
        question=str(result["question"]),
        grounding_source=result.get("grounding_source"),
    )
    db.add(first_turn)
    await db.commit()

    return InterviewStartResponse(
        session_id=session.id,
        question=str(result["question"]),
        turn_number=1,
        total_turns=total_turns,
        grounding_source=str(result.get("grounding_source") or "generic"),
    )


# ── Endpoint 2: POST /interview/{id}/answer (SSE) ───────────────────


async def _fetch_session_and_turns(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[InterviewSession, list[InterviewTurn]]:
    """Fetch session scoped to user + all turns ordered by turn_number.

    Raises 404 when the session doesn't exist or belongs to another user.
    Kept as a helper because the answer / get / abandon / save-gaps
    endpoints all need the same bounded fetch with the same ownership
    check.
    """

    session = await db.get(InterviewSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="Interview session not found")

    result = await db.execute(
        select(InterviewTurn)
        .where(InterviewTurn.session_id == session_id)
        .order_by(InterviewTurn.turn_number.asc())
    )
    turns = list(result.scalars().all())
    return session, turns


def _turns_to_wire_list(turns: list[InterviewTurn]) -> list[TurnResponse]:
    """Map ORM turns to wire schema list in turn-number order."""

    return [_turn_to_response(t) for t in turns]


@router.post(
    "/interview/{session_id}/answer",
    summary="Submit an answer — SSE stream of rubric + next-question / completion",
    description=(
        "SSE event sequence: ``rubric`` with the graded dimensions, then "
        "either ``next_question`` (new Q for the next turn) or "
        "``completed`` (inline-math summary). Returns HTTP 409 when the "
        "session is not in_progress or the latest turn is already graded."
    ),
)
async def answer_interview(
    session_id: uuid.UUID,
    body: InterviewAnswerRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grade the current answer and advance (or close) the session via SSE."""

    # Resolve target turn / session up-front so 404 / 409 happen *before*
    # we open the SSE pipe — mirrors the chat router's "validate, then
    # stream" contract.
    session, turns = await _fetch_session_and_turns(db, session_id, user.id)

    if session.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "session_closed",
                "detail": f"Session is {session.status}; cannot submit answer",
            },
        )

    if not turns:
        raise HTTPException(
            status_code=409,
            detail={"error": "no_turn", "detail": "Session has no active turn"},
        )

    current_turn = turns[-1]
    if current_turn.rubric_scores_json is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_graded",
                "detail": "Latest turn is already graded; refresh to get next Q",
            },
        )

    answer_text = body.answer_text
    session_factory = (
        getattr(request.app.state, "test_session_factory", None) or async_session
    )

    # Snapshot the fields we need from the current turn *before* the
    # generator runs — SQLAlchemy instance attrs become unsafe across
    # session boundaries and we're about to open a fresh session inside
    # the generator for commit durability.
    current_turn_id = current_turn.id
    current_turn_created = current_turn.created_at
    prev_questions = [t.question for t in turns]

    async def event_generator():
        """SSE generator — reads with a fresh DB session per event block.

        We deliberately use ``session_factory()`` (matching ``chat.py``'s
        persistence trick) because the request-scoped ``db`` gets closed
        as soon as FastAPI finishes the handler and the SSE loop runs
        outside that scope.
        """

        agent = _InterviewerAgent()
        ctx = AgentContext(
            user_id=user.id,
            course_id=session.course_id or uuid.uuid4(),
        )

        # ── 1. Grade the current answer ──
        try:
            rubric = await agent.grade_answer(
                ctx,
                question=current_turn.question,
                answer=answer_text,
                mode=session.mode,
            )
        except Exception as exc:  # noqa: BLE001 — SSE stream must not 500
            logger.exception("interview_grade_failed session=%s", session_id)
            yield {
                "event": "error",
                "data": json.dumps({"error": "grade_failed", "detail": str(exc)[:200]}),
            }
            return

        # Persist the answer + rubric. Use the time snapshot so
        # ``answer_time_ms`` matches "time from Q created to A submitted".
        rubric_dict = rubric.model_dump(mode="json")
        answer_time_ms: int | None
        if current_turn_created is not None:
            now_utc = datetime.now(timezone.utc)
            delta = now_utc - current_turn_created
            answer_time_ms = int(delta.total_seconds() * 1000)
        else:
            answer_time_ms = None

        async with session_factory() as persist_db:
            db_turn = await persist_db.get(InterviewTurn, current_turn_id)
            if db_turn is not None:
                db_turn.answer = answer_text
                db_turn.rubric_scores_json = rubric_dict
                db_turn.rubric_feedback_short = rubric.feedback_short
                db_turn.answer_time_ms = answer_time_ms
            db_session = await persist_db.get(InterviewSession, session_id)
            if db_session is not None:
                db_session.completed_turns = (db_session.completed_turns or 0) + 1
            await persist_db.commit()

        yield {
            "event": "rubric",
            "data": json.dumps(
                {
                    "turn_number": current_turn.turn_number,
                    "dimensions": {
                        name: {"score": score.score, "feedback": score.feedback}
                        for name, score in rubric.dimensions.items()
                    },
                    "feedback_short": rubric.feedback_short,
                }
            ),
        }

        # ── 2. Decide — advance or complete ──
        async with session_factory() as refresh_db:
            refreshed = await refresh_db.get(InterviewSession, session_id)
            if refreshed is None:
                return
            completed = refreshed.completed_turns or 0
            total = refreshed.total_turns

            if completed < total:
                # Generate + persist the next turn.
                next_turn_number = completed + 1
                next_type = _question_type_for_turn(session.mode, next_turn_number)
                try:
                    q_result = await agent.generate_question(
                        ctx,
                        turn_number=next_turn_number,
                        total_turns=total,
                        project_focus=session.project_focus,
                        mode=session.mode,
                        question_type=next_type,
                        prev_questions=prev_questions,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("interview_next_q_failed session=%s", session_id)
                    yield {
                        "event": "error",
                        "data": json.dumps(
                            {"error": "next_q_failed", "detail": str(exc)[:200]}
                        ),
                    }
                    return

                next_turn = InterviewTurn(
                    session_id=session_id,
                    turn_number=next_turn_number,
                    question_type=str(q_result.get("question_type") or next_type),
                    question=str(q_result["question"]),
                    grounding_source=q_result.get("grounding_source"),
                )
                refresh_db.add(next_turn)
                await refresh_db.commit()

                yield {
                    "event": "next_question",
                    "data": json.dumps(
                        {
                            "turn_number": next_turn_number,
                            "total_turns": total,
                            "question": str(q_result["question"]),
                            "grounding_source": str(
                                q_result.get("grounding_source") or "generic"
                            ),
                        }
                    ),
                }
            else:
                # Session done — inline-math summary + SSE ``completed``.
                all_turns_result = await refresh_db.execute(
                    select(InterviewTurn)
                    .where(InterviewTurn.session_id == session_id)
                    .order_by(InterviewTurn.turn_number.asc())
                )
                all_turns = list(all_turns_result.scalars().all())
                summary = agent.write_summary_inline(_turns_to_wire_list(all_turns))
                summary = _attach_worst_turn_id(summary, all_turns)

                refreshed.status = "completed"
                refreshed.completed_at = datetime.now(timezone.utc)
                refreshed.summary_json = json.loads(summary.model_dump_json())
                await refresh_db.commit()

                yield {
                    "event": "completed",
                    "data": json.dumps(
                        {
                            "session_id": str(session_id),
                            "summary": json.loads(summary.model_dump_json()),
                        }
                    ),
                }

    return EventSourceResponse(event_generator())


# ── Endpoint 3: GET /interview/{id} ─────────────────────────────────


@router.get(
    "/interview/{session_id}",
    response_model=InterviewSessionStateResponse,
    summary="Rehydrate a full interview session (pause/resume)",
)
async def get_interview(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InterviewSessionStateResponse:
    """Return the complete session state — session row + every turn + summary."""

    session, turns = await _fetch_session_and_turns(db, session_id, user.id)

    summary: SummaryResponse | None = None
    if isinstance(session.summary_json, dict):
        try:
            summary = SummaryResponse.model_validate(session.summary_json)
        except ValueError:
            logger.warning(
                "interview_summary_validate_fail session=%s",
                session.id,
            )

    # ``session.status`` is a plain ``str`` on the ORM side; pydantic
    # validates it against the 4-value Literal at construction time.
    # ``model_validate`` keeps that contract without a blind cast.
    return InterviewSessionStateResponse.model_validate(
        {
            "session_id": session.id,
            "status": session.status,
            "mode": session.mode,
            "duration": session.duration,
            "project_focus": session.project_focus,
            "total_turns": session.total_turns,
            "completed_turns": session.completed_turns or 0,
            "turns": [t.model_dump() for t in _turns_to_wire_list(turns)],
            "summary": summary.model_dump() if summary else None,
        }
    )


# ── Endpoint 4: POST /interview/{id}/abandon ────────────────────────


@router.post(
    "/interview/{session_id}/abandon",
    response_model=AbandonResponse,
    summary="End an interview session early with a partial summary",
)
async def abandon_interview(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AbandonResponse:
    """Mark the session ``completed_early`` and return the inline-math summary."""

    session, turns = await _fetch_session_and_turns(db, session_id, user.id)

    if session.status not in {"in_progress"}:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "session_closed",
                "detail": f"Session already {session.status}",
            },
        )

    # Summary from graded turns only — ungraded turns stay invisible.
    agent = _InterviewerAgent()
    graded_only = [t for t in turns if t.rubric_scores_json is not None]
    summary = agent.write_summary_inline(_turns_to_wire_list(graded_only))
    summary = _attach_worst_turn_id(summary, graded_only)

    session.status = "completed_early"
    session.completed_at = datetime.now(timezone.utc)
    session.summary_json = json.loads(summary.model_dump_json())
    await db.commit()

    return AbandonResponse(session_id=session.id, summary=summary)


# ── Endpoint 5: POST /interview/{id}/save-gaps ──────────────────────


@router.post(
    "/interview/{session_id}/save-gaps",
    response_model=SaveGapsResponse,
    summary="Spawn flashcards from selected interview turns",
    description=(
        "For each selected ``turn_id`` we build a :class:`CardCandidate` "
        "(``front=question``, ``back=rubric_feedback_short``) and hand the "
        "batch to §14.5 ``save-candidates`` in-process. T5 will flip the "
        "``spawn_origin`` to ``'interview'`` once the Literal is extended."
    ),
)
async def save_interview_gaps(
    session_id: uuid.UUID,
    body: SaveGapsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SaveGapsResponse:
    """Convert graded turns into flashcards via the shared save-candidates path."""

    session, turns = await _fetch_session_and_turns(db, session_id, user.id)

    if session.course_id is None:
        # Save-candidates is course-scoped; without a course_id we can't
        # route the cards anywhere meaningful. Reject explicitly rather
        # than silently no-op so the frontend knows to ask for a course.
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_course",
                "detail": "Session has no course_id — cannot save gap cards",
            },
        )

    wanted: set[uuid.UUID] = set(body.turn_ids)
    selected = [t for t in turns if t.id in wanted]
    if not selected:
        raise HTTPException(
            status_code=400,
            detail={"error": "no_turns", "detail": "No matching turns found"},
        )

    candidates: list[CardCandidate] = []
    for turn in selected:
        # Prefix with ``Revisit:`` so the card stands out from regular
        # tutor-turn cards when it shows up in ``/due``. ``back`` is the
        # grader's short feedback (typ. 2-3 sentences) — the best available
        # "what to study next" signal without an extra LLM call.
        front = f"Revisit: {turn.question}"[:200]
        back = turn.rubric_feedback_short or "No feedback captured."
        candidates.append(
            CardCandidate(
                front=front,
                back=back[:500],
                concept_slug=None,
                screenshot_hash=None,
            )
        )

    # T5 wired: the Literal now accepts ``"interview"`` and
    # ``interview_session_id`` propagates into ``problem_metadata`` on the
    # write side (see ``routers/curriculum.save_flashcard_candidates``).
    save_req = SaveCandidatesRequest(
        candidates=candidates,
        spawn_origin="interview",
        interview_session_id=session_id,
    )

    result = await _save_flashcard_candidates(
        course_id=session.course_id,
        body=save_req,
        user=user,
        db=db,
    )

    return SaveGapsResponse(
        saved_count=result.count,
        problem_ids=list(result.saved_problem_ids),
    )


__all__ = ["router"]
