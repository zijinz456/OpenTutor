"""Standard PathRoom factory — Phase 16b Bundle A.

Two-stage LLM pipeline that produces and persists a single
``PathRoom`` plus its ``PracticeProblem`` task rows for the existing
schema (see ``models/learning_path.py`` + ``models/practice.py``).

Design echoes ``services/curriculum/syllabus_builder.py`` and
``services/practice/lab_grader.py``:

* JSON-only LLM contract.
* ``_extract_json_object`` to forgive markdown fences/trailing prose.
* pydantic validation with **retry once** per stage.
* Fakeable LLM client: tests pass an ``llm_client`` kwarg, or override
  the module-level ``LLM_CLIENT`` reference. No real network in tests.

What this module owns
---------------------
* Pydantic schemas for the two LLM stages (outline → full payload).
* ``compute_generation_seed`` — deterministic sha256 of the request.
* ``generate_and_persist_room`` — the public entry point used by the
  router (Subagent B).

What this module deliberately does NOT do
-----------------------------------------
* No HTTP/router code (Subagent B owns that).
* No SSE / job-store work (lives in ``path_room_job_store``).
* No quota / rate-limit check (router-level concern).
* No path/course coherence check (router-level concern). The factory
  trusts its caller.
* No new DB migration. Persists into existing tables only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.learning_path import PathRoom
from models.practice import PracticeProblem
from scripts.path_capstones import backfill_room_capstones

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────

# Idempotence window: identical seed within this delta returns the
# existing room instead of generating a new one. Spec says 1 hour.
IDEMPOTENCE_WINDOW = timedelta(hours=1)

# Allowed question_type values for **generated** rooms in this slice.
# Mirrors spec Part B.9. ``lab_exercise`` is intentionally excluded —
# hacking labs have their own factory.
ALLOWED_QUESTION_TYPES: frozenset[str] = frozenset(
    {
        "mc",
        "fill_blank",
        "free_response",
        "trace",
        "apply",
        "compare",
        "rebuild",
        "code_exercise",
    }
)

# Two-attempt retry budget per LLM stage (one initial + one retry).
_MAX_ATTEMPTS = 2

# Length cap on the topic component of the seed; matches router-level
# trim+validate (3..120 chars). Kept here as a safety net.
_TOPIC_MAX_LEN = 120

# Default model label persisted to ``PathRoom.generator_model`` when the
# fake client doesn't surface one. Real clients should expose ``.model``.
_DEFAULT_MODEL_LABEL = "unknown"

# Slug helpers — collapsing topic to a deterministic, URL-safe stem.
_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


# ── LLM client protocol ─────────────────────────────────────────────


class _LLMClient(Protocol):
    """Minimal surface the factory uses.

    The real ``services.llm.router.get_llm_client("fast")`` already
    satisfies this. Tests inject a fake.
    """

    async def extract(
        self, system_prompt: str, user_message: str
    ) -> tuple[str, dict[str, Any]]: ...


# Module-level override hook — tests may set this to a fake before
# calling ``generate_and_persist_room``. ``None`` means "use the real
# router"; an explicit ``llm_client=`` kwarg still wins.
LLM_CLIENT: _LLMClient | None = None


def _resolve_llm_client(override: _LLMClient | None) -> _LLMClient:
    """Pick the LLM client to use for this generation run.

    Priority: explicit kwarg > module-level ``LLM_CLIENT`` > real router.
    Imported lazily so the module doesn't pull provider config at import
    time — important for unit tests that never hit the network.
    """

    if override is not None:
        return override
    if LLM_CLIENT is not None:
        return LLM_CLIENT
    # Lazy import: avoids forcing ``config.settings`` on test collection.
    from services.llm.router import get_llm_client

    return get_llm_client("fast")


# ── Schemas — stage 1 outline ────────────────────────────────────────


class RoomOutline(BaseModel):
    """Stage-1 LLM output. Concept-level scaffolding for the room."""

    title: str = Field(..., min_length=3, max_length=200)
    intro_excerpt: str = Field(..., min_length=10, max_length=4000)
    outcome: str = Field(..., min_length=5, max_length=400)
    module_label: str = Field(..., min_length=2, max_length=80)
    learning_objectives: list[str] = Field(...)

    @field_validator("learning_objectives")
    @classmethod
    def _exactly_three(cls, value: list[str]) -> list[str]:
        # Spec Part B.4: exactly 3 short objectives.
        if len(value) != 3:
            raise ValueError("learning_objectives must contain exactly 3 items")
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "learning_objectives entries must be non-empty strings"
                )
        return [item.strip() for item in value]


# ── Schemas — stage 2 full room ──────────────────────────────────────


_QType = Literal[
    "mc",
    "fill_blank",
    "free_response",
    "trace",
    "apply",
    "compare",
    "rebuild",
    "code_exercise",
]


class GeneratedTask(BaseModel):
    """One LLM-generated task. Becomes a ``PracticeProblem`` row."""

    title: str = Field(..., min_length=3, max_length=200)
    question_type: _QType
    question: str = Field(..., min_length=3)
    correct_answer: str = Field(..., min_length=1)
    explanation: str = Field(..., min_length=3)
    hints: list[str] = Field(...)
    difficulty_layer: Literal[1, 2, 3]
    is_capstone: bool

    @field_validator("hints")
    @classmethod
    def _hints_two_or_three(cls, value: list[str]) -> list[str]:
        # Spec Part B.6: hints list length 2 or 3.
        if len(value) not in (2, 3):
            raise ValueError("hints must contain 2 or 3 items")
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("hint entries must be non-empty strings")
        return [item.strip() for item in value]


class RoomPayload(BaseModel):
    """Stage-2 LLM output. Wraps the full ordered task list."""

    tasks: list[GeneratedTask]


def _validate_task_count(payload: RoomPayload, expected_count: int) -> None:
    """Raise ``ValueError`` if the task list is the wrong size or has the
    wrong number of capstones.

    Doing this **outside** pydantic — we don't know ``expected_count``
    at class-definition time, and we want to enforce capstone-count too.
    """

    if len(payload.tasks) != expected_count:
        raise ValueError(
            f"expected exactly {expected_count} tasks, got {len(payload.tasks)}"
        )
    capstone_count = sum(1 for task in payload.tasks if task.is_capstone)
    if capstone_count != 1:
        raise ValueError(f"expected exactly 1 capstone task, got {capstone_count}")


# ── Seed + slug helpers ──────────────────────────────────────────────


def compute_generation_seed(
    *,
    user_id: uuid.UUID,
    path_id: uuid.UUID,
    course_id: uuid.UUID,
    topic: str,
    difficulty: str,
    task_count: int,
) -> str:
    """sha256 hex of canonical request inputs.

    Canonical form (joined with ``|``):
    ``user_id``, ``path_id``, ``course_id``, ``topic.strip().lower()``,
    ``difficulty``, ``task_count``.

    Trimming + lowercasing the topic so cosmetic edits ("Lists" vs
    " lists ") don't bypass idempotence.
    """

    topic_canon = (topic or "").strip().lower()
    if len(topic_canon) > _TOPIC_MAX_LEN:
        topic_canon = topic_canon[:_TOPIC_MAX_LEN]
    canonical = (
        f"{user_id}|{path_id}|{course_id}|{topic_canon}|{difficulty}|{task_count}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _topic_slug_stem(topic: str) -> str:
    """Lower-kebab stem of the topic (max 40 chars), no leading/trailing dashes."""

    raw = (topic or "generated").strip().lower()
    stem = _SLUG_NON_WORD.sub("-", raw).strip("-")
    if not stem:
        stem = "generated"
    return stem[:40].rstrip("-") or "generated"


async def _make_unique_room_slug(
    db: AsyncSession,
    *,
    path_id: uuid.UUID,
    topic: str,
    seed_hex: str,
) -> str:
    """Deterministic, collision-safe slug within a path.

    Format: ``<topic-stem>-<seed-suffix>``. If somehow already taken
    (extremely unlikely — sha collision in the same path), append an
    increasing numeric tail.
    """

    base = _topic_slug_stem(topic)
    suffix = seed_hex[:8]
    candidate = f"{base}-{suffix}"
    # Hard cap at 80 chars (PathRoom.slug column width).
    if len(candidate) > 80:
        candidate = candidate[:80].rstrip("-")

    extra = 0
    while True:
        existing = await db.execute(
            select(PathRoom).where(
                PathRoom.path_id == path_id, PathRoom.slug == candidate
            )
        )
        if existing.scalar_one_or_none() is None:
            return candidate
        extra += 1
        candidate = f"{base}-{suffix}-{extra}"
        if len(candidate) > 80:
            candidate = candidate[:80].rstrip("-")


# ── JSON parsing ─────────────────────────────────────────────────────


def _extract_json_object(raw: str) -> str | None:
    """Carve a JSON object out of an LLM response.

    Same pattern as ``syllabus_builder._extract_json_object``: take the
    span from the first ``{`` to the last ``}``. ``json.loads`` on the
    result is still the source of truth.
    """

    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    return raw[start : end + 1]


# ── Prompts ──────────────────────────────────────────────────────────


_OUTLINE_SYSTEM = (
    "You are a curriculum designer producing concise room outlines for a "
    "TryHackMe-style learning platform. Output ONLY valid JSON matching "
    "the schema in the user message. No markdown fences. No prose."
)


def _build_outline_prompt(*, topic: str, difficulty: str, task_count: int) -> str:
    """Stage-1 user prompt. Asks for the room scaffolding only."""

    return (
        "Produce a JSON outline for a single learning room.\n\n"
        "Schema:\n"
        "{\n"
        '  "title": "<= 200 chars",\n'
        '  "intro_excerpt": "1-3 short paragraphs introducing the topic",\n'
        '  "outcome": "one-sentence practical outcome",\n'
        '  "module_label": "short grouping label like Basics or Advanced",\n'
        '  "learning_objectives": ["objective 1", "objective 2", "objective 3"]\n'
        "}\n\n"
        "Hard rules:\n"
        "- Exactly 3 learning_objectives.\n"
        "- intro_excerpt must be <= 4000 chars.\n"
        "- Topic / difficulty / task_count are inputs, not output keys.\n"
        f"\nTopic: {topic}\n"
        f"Difficulty: {difficulty}\n"
        f"Planned task count: {task_count}\n"
    )


_TASKS_SYSTEM = (
    "You write practice tasks for a learning room. Output ONLY valid "
    "JSON matching the schema in the user message. No markdown fences. "
    "No prose."
)


def _build_tasks_prompt(
    *,
    outline: RoomOutline,
    difficulty: str,
    task_count: int,
) -> str:
    """Stage-2 user prompt. Includes the outline so tasks stay coherent."""

    layer_guidance = _difficulty_guidance(difficulty)
    allowed_types = ", ".join(sorted(ALLOWED_QUESTION_TYPES))
    objectives_json = json.dumps(outline.learning_objectives)
    return (
        "Produce a JSON object listing the practice tasks for this room.\n\n"
        "Schema:\n"
        "{\n"
        '  "tasks": [\n'
        "    {\n"
        '      "title": "<= 200 chars",\n'
        f'      "question_type": "<one of: {allowed_types}>",\n'
        '      "question": "the prompt the learner sees",\n'
        '      "correct_answer": "the canonical correct answer",\n'
        '      "explanation": "why the correct answer is correct",\n'
        '      "hints": ["hint 1", "hint 2"],\n'
        '      "difficulty_layer": 1,\n'
        '      "is_capstone": false\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Hard rules:\n"
        f"- Exactly {task_count} tasks.\n"
        "- Exactly one task has is_capstone=true; it MUST be the final, "
        "  hardest task in the list.\n"
        "- difficulty_layer is 1, 2, or 3.\n"
        f"- {layer_guidance}\n"
        "- hints contains 2 or 3 entries.\n"
        f"- question_type is one of: {allowed_types}. NEVER lab_exercise.\n"
        "\n"
        f"Room title: {outline.title}\n"
        f"Module label: {outline.module_label}\n"
        f"Outcome: {outline.outcome}\n"
        f"Learning objectives: {objectives_json}\n"
        f"Difficulty band: {difficulty}\n"
    )


def _difficulty_guidance(difficulty: str) -> str:
    """Deterministic mapping of difficulty band to layer expectations.

    Spec Part B.11. We push this into the prompt rather than rewriting
    layers post-hoc — the LLM already chose, the validator already passed.
    """

    band = (difficulty or "").lower()
    if band == "beginner":
        return "Most tasks should be difficulty_layer=1; the capstone may be 2."
    if band == "intermediate":
        return "Mix difficulty_layer values across 1, 2, and 3."
    if band == "advanced":
        return "Most tasks should be difficulty_layer=2 or 3."
    # Default: behave like intermediate. Router validates the band, so
    # this branch is defensive only.
    return "Mix difficulty_layer values across 1, 2, and 3."


# ── LLM call helpers ─────────────────────────────────────────────────


async def _call_llm_once(
    client: _LLMClient, system_prompt: str, user_prompt: str
) -> str | None:
    """One round-trip. Returns the raw string or ``None`` on transport error."""

    try:
        raw, _ = await client.extract(system_prompt, user_prompt)
    except (ConnectionError, TimeoutError) as exc:
        logger.warning("path_room_factory: LLM network error (%s)", exc)
        return None
    except (ValueError, RuntimeError) as exc:
        logger.warning("path_room_factory: LLM call failed (%s)", exc)
        return None
    return raw


async def _generate_outline(
    client: _LLMClient, *, topic: str, difficulty: str, task_count: int
) -> RoomOutline:
    """Run stage 1 with one retry. Raises on terminal failure."""

    system = _OUTLINE_SYSTEM
    user = _build_outline_prompt(
        topic=topic, difficulty=difficulty, task_count=task_count
    )
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        raw = await _call_llm_once(client, system, user)
        if raw is None:
            last_error = RuntimeError("LLM transport failure")
            continue
        blob = _extract_json_object(raw)
        if blob is None:
            last_error = ValueError("no JSON object found in outline response")
            logger.info(
                "path_room_factory: outline attempt %d/%d malformed",
                attempt + 1,
                _MAX_ATTEMPTS,
            )
            continue
        try:
            obj = json.loads(blob)
            return RoomOutline.model_validate(obj)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            logger.info(
                "path_room_factory: outline attempt %d/%d invalid (%s)",
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
            )
            continue
    raise RuntimeError(
        f"outline generation failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    )


async def _generate_tasks(
    client: _LLMClient,
    *,
    outline: RoomOutline,
    difficulty: str,
    task_count: int,
) -> RoomPayload:
    """Run stage 2 with one retry. Raises on terminal failure."""

    system = _TASKS_SYSTEM
    user = _build_tasks_prompt(
        outline=outline, difficulty=difficulty, task_count=task_count
    )
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        raw = await _call_llm_once(client, system, user)
        if raw is None:
            last_error = RuntimeError("LLM transport failure")
            continue
        blob = _extract_json_object(raw)
        if blob is None:
            last_error = ValueError("no JSON object found in tasks response")
            logger.info(
                "path_room_factory: tasks attempt %d/%d malformed",
                attempt + 1,
                _MAX_ATTEMPTS,
            )
            continue
        try:
            obj = json.loads(blob)
            payload = RoomPayload.model_validate(obj)
            _validate_task_count(payload, task_count)
            return payload
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            logger.info(
                "path_room_factory: tasks attempt %d/%d invalid (%s)",
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
            )
            continue
    raise RuntimeError(
        f"tasks generation failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    )


# ── Persistence helpers ──────────────────────────────────────────────


def _reorder_capstone_last(tasks: list[GeneratedTask]) -> list[GeneratedTask]:
    """Move the unique capstone task to the end, preserving the rest's order.

    Spec Part B.8 — the capstone must be the LAST task. The LLM is
    instructed to do this; we still enforce it post-hoc so a misordered
    response doesn't poison the persisted ordering.
    """

    non_capstones = [t for t in tasks if not t.is_capstone]
    capstones = [t for t in tasks if t.is_capstone]
    # ``_validate_task_count`` already guarantees exactly one capstone.
    return non_capstones + capstones


def _resolve_model_label(client: _LLMClient) -> str:
    """Best-effort model label for ``PathRoom.generator_model``.

    Real router clients expose a ``.model`` attribute; fakes may not.
    Falls back to the default label so the column is never NULL on a
    successfully generated room.
    """

    label = getattr(client, "model", None) or getattr(client, "model_name", None)
    if isinstance(label, str) and label.strip():
        return label.strip()[:100]
    return _DEFAULT_MODEL_LABEL


async def _next_room_order(db: AsyncSession, path_id: uuid.UUID) -> int:
    """Return ``max(room_order) + 1`` within a path, or 0 if empty."""

    rows = (
        (
            await db.execute(
                select(PathRoom.room_order).where(PathRoom.path_id == path_id)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    return max(rows) + 1


async def _find_existing_by_seed(
    db: AsyncSession, *, path_id: uuid.UUID, seed_hex: str
) -> PathRoom | None:
    """Idempotent reuse: fresh generated room with the same seed in this path.

    Spec Part B.13: same ``generation_seed`` AND created within
    ``IDEMPOTENCE_WINDOW`` AND same path_id → reuse.
    """

    stmt = select(PathRoom).where(
        PathRoom.path_id == path_id,
        PathRoom.generation_seed == seed_hex,
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    if not candidates:
        return None

    cutoff = datetime.now(timezone.utc) - IDEMPOTENCE_WINDOW
    fresh: list[PathRoom] = []
    for room in candidates:
        generated_at = room.generated_at
        if generated_at is None:
            continue
        # SQLite + aiosqlite returns naive datetimes; treat as UTC.
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        if generated_at >= cutoff:
            fresh.append(room)

    if not fresh:
        return None
    # Most recent wins (stable behaviour if somehow multiple exist).
    fresh.sort(
        key=lambda r: r.generated_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return fresh[0]


# ── Public API ───────────────────────────────────────────────────────


async def generate_and_persist_room(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    path_id: uuid.UUID,
    course_id: uuid.UUID,
    topic: str,
    difficulty: str,
    task_count: int,
    llm_client: _LLMClient | None = None,
) -> PathRoom:
    """Run the two-stage generation pipeline and persist the result.

    Behaviour summary
    -----------------
    1. Compute the deterministic ``generation_seed``.
    2. **Idempotence:** if a recent (< 1h) ``PathRoom`` with the same
       seed and path already exists, return it without calling the LLM
       and without inserting anything new. The router decides whether
       to surface ``reused=true`` to the client.
    3. Stage 1: outline (retry-once). Raises ``RuntimeError`` if both
       attempts fail.
    4. Stage 2: tasks (retry-once + size/capstone validation). Raises
       ``RuntimeError`` if both attempts fail.
    5. Move the capstone task to the end of the persisted order.
    6. Insert one ``PathRoom`` row + ``task_count`` ``PracticeProblem``
       rows. ``commit`` happens once, atomically.
    7. Trigger ``backfill_room_capstones`` for the new room so the
       ``capstone_problem_ids`` column is populated immediately.

    On any failure during steps 3-6 the session is rolled back so no
    partial state survives (spec Part B.14).

    Args:
        db: Session owned by the caller. The factory commits on its own.
        user_id: Owning user — only used for the seed canonical form.
        path_id: Existing ``LearningPath.id``. NOT NULL on the row.
        course_id: ``Course.id`` to attach every generated task to.
        topic: Free-form topic the learner wants a room about.
        difficulty: ``"beginner" | "intermediate" | "advanced"``.
        task_count: Number of tasks to generate (router enforces 3..8).
        llm_client: Optional injected LLM client (tests). Falls back to
            module-level ``LLM_CLIENT`` then to the real router.

    Returns:
        The persisted (or reused) ``PathRoom`` ORM instance, refreshed
        with its server-side defaults.
    """

    seed_hex = compute_generation_seed(
        user_id=user_id,
        path_id=path_id,
        course_id=course_id,
        topic=topic,
        difficulty=difficulty,
        task_count=task_count,
    )

    existing = await _find_existing_by_seed(db, path_id=path_id, seed_hex=seed_hex)
    if existing is not None:
        logger.info(
            "path_room_factory: reusing room %s for seed %s",
            existing.id,
            seed_hex[:12],
        )
        return existing

    client = _resolve_llm_client(llm_client)

    try:
        outline = await _generate_outline(
            client, topic=topic, difficulty=difficulty, task_count=task_count
        )
        payload = await _generate_tasks(
            client,
            outline=outline,
            difficulty=difficulty,
            task_count=task_count,
        )
    except Exception:
        # No DB writes happened yet, but rollback to be defensive — the
        # caller may have started a transaction we don't know about.
        await db.rollback()
        raise

    ordered_tasks = _reorder_capstone_last(payload.tasks)

    try:
        slug = await _make_unique_room_slug(
            db, path_id=path_id, topic=topic, seed_hex=seed_hex
        )
        room_order = await _next_room_order(db, path_id)
        now_utc = datetime.now(timezone.utc)

        new_room = PathRoom(
            id=uuid.uuid4(),
            path_id=path_id,
            slug=slug,
            title=outline.title,
            room_order=room_order,
            intro_excerpt=outline.intro_excerpt,
            outcome=outline.outcome,
            module_label=outline.module_label,
            task_count_target=task_count,
            generated_at=now_utc,
            generator_model=_resolve_model_label(client),
            generation_seed=seed_hex,
            room_type="generated",
        )
        db.add(new_room)
        # Flush so ``new_room.id`` is committed-shape and FKs resolve.
        await db.flush()

        objectives = outline.learning_objectives
        for index, task in enumerate(ordered_tasks):
            # Spec: ``problem_metadata.learning_objective`` is matched by
            # index and **loops** if more tasks than objectives.
            objective = objectives[index % len(objectives)]
            metadata: dict[str, Any] = {
                "generated_seed": seed_hex,
                "is_capstone": bool(task.is_capstone),
                "learning_objective": objective,
                "hints": list(task.hints),
                "generated_room_title": outline.title,
            }
            db.add(
                PracticeProblem(
                    id=uuid.uuid4(),
                    course_id=course_id,
                    path_room_id=new_room.id,
                    task_order=index,
                    order_index=index,
                    question_type=task.question_type,
                    question=task.question,
                    correct_answer=task.correct_answer,
                    explanation=task.explanation,
                    difficulty_layer=task.difficulty_layer,
                    source="ai_generated",
                    problem_metadata=metadata,
                )
            )

        await db.flush()
        # Capstone backfill BEFORE commit — it mutates ``new_room`` in
        # the same session, and we want one atomic commit.
        await backfill_room_capstones(db, room_ids=[new_room.id])
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await db.refresh(new_room)
    return new_room


__all__ = [
    "ALLOWED_QUESTION_TYPES",
    "GeneratedTask",
    "IDEMPOTENCE_WINDOW",
    "LLM_CLIENT",
    "RoomOutline",
    "RoomPayload",
    "compute_generation_seed",
    "generate_and_persist_room",
]
