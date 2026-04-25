"""Compiled-drill-course loader — Phase 16c practice-first pivot (T5).

Reads a versioned YAML course tree at
``content/drills/{course_slug}/v{version}/course.yaml`` and upserts the
content into the ``drill_courses`` / ``drill_modules`` / ``drills``
tables. **No LLM generation at request time** — every drill is compiled
ahead of time and committed under ``content/drills/``.

Idempotency
-----------

The loader is safe to re-run — it matches on stable slugs:

* ``DrillCourse`` by ``(slug,)`` (courses are globally unique).
* ``DrillModule`` by ``(course_id, slug)``.
* ``Drill`` by ``(module_id, slug)``.

Existing rows are updated in place; new rows are inserted. Rows that
exist in DB but are missing from the YAML are *not* deleted — content
removal is a deliberate action, not a side effect of renaming a slug
upstream.

Hidden tests & reference solution
---------------------------------

``hidden_tests`` lives in the DB (server-only; routers NEVER return it).
``reference_solution`` does **not** have a column (critic C3) — it lives
only in the YAML. At seed time we run
:func:`_validate_at_load` which executes the canonical solution against
its own hidden tests to guarantee the YAML's "answer key" actually
passes. The reference solution is then discarded and never surfaced.

Threat model: the YAML is trusted author content committed to the repo.
We still execute the validation in a subprocess sandbox (re-using
:mod:`services.drill_runner`) because a broken YAML is better caught
as a sandboxed failure than an in-process import blow-up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.drill import Drill, DrillCourse, DrillModule


# ── YAML path resolution ────────────────────────────────────────────


def _locate_course_yaml(course_slug: str, version: str) -> Path | None:
    """Walk up from ``__file__`` looking for the compiled course YAML.

    Mirrors :func:`scripts.seed_python_paths._locate_curriculum_yaml`:
    the repo root vs ``apps/api`` working directory differs between
    container, local-run, and test-run contexts, so we climb up to 8
    levels looking for ``content/drills/{slug}/v{version}/course.yaml``.

    Returns ``None`` when nothing matches so the caller can emit a clear
    error with the searched slug rather than a bare ``FileNotFoundError``.
    """

    current = Path(__file__).resolve().parent
    version_variants = list(
        dict.fromkeys(
            [
                version,
                f"v{version}" if not version.startswith("v") else version[1:],
            ]
        )
    )
    for _ in range(8):
        for version_dir in version_variants:
            rel = Path("content") / "drills" / course_slug / version_dir / "course.yaml"
            candidate = current / rel
            if candidate.is_file():
                return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


# ── Schema guards ───────────────────────────────────────────────────


_REQUIRED_DRILL_KEYS = frozenset(
    {
        "slug",
        "title",
        "why_it_matters",
        "starter_code",
        "hidden_tests",
        "reference_solution",
        "hints",
        "skill_tags",
        "source_citation",
        "time_budget_min",
        "difficulty_layer",
    }
)


def _validate_yaml(data: dict[str, Any]) -> None:
    """Shape-check the loaded course document before touching the DB.

    Fail loud and early — a malformed YAML is an author bug, not a
    runtime edge case. Messages include the slug/path of the offending
    entry so the author can fix it without grepping.
    """

    if not isinstance(data, dict):
        raise ValueError("course.yaml root must be a mapping")

    for key in ("slug", "title", "source", "version", "modules"):
        if key not in data:
            raise ValueError(f"course.yaml missing top-level key: {key!r}")

    if not isinstance(data["modules"], list) or not data["modules"]:
        raise ValueError("course.yaml 'modules' must be a non-empty list")

    modules = data["modules"]
    seen_module_slugs: set[str] = set()
    for mi, raw_module in enumerate(modules):
        if not isinstance(raw_module, dict):
            raise ValueError(f"module[{mi}] must be a mapping")
        module = cast(dict[str, Any], raw_module)
        for key in ("slug", "title", "order_index", "drills"):
            if key not in module:
                raise ValueError(f"module[{mi}] missing key: {key!r}")
        module_slug = str(module["slug"])
        if module_slug in seen_module_slugs:
            raise ValueError(f"duplicate module slug: {module_slug!r}")
        seen_module_slugs.add(module_slug)
        if not isinstance(module["drills"], list) or not module["drills"]:
            raise ValueError(
                f"module[{module_slug!r}] 'drills' must be a non-empty list"
            )

        seen_drill_slugs: set[str] = set()
        for di, raw_drill in enumerate(module["drills"]):
            if not isinstance(raw_drill, dict):
                raise ValueError(
                    f"module[{module_slug!r}].drills[{di}] must be a mapping"
                )
            drill = cast(dict[str, Any], raw_drill)
            missing = _REQUIRED_DRILL_KEYS - set(drill.keys())
            if missing:
                raise ValueError(
                    f"module[{module_slug!r}].drills[{di}] missing keys: "
                    f"{sorted(missing)!r}"
                )
            drill_slug = str(drill["slug"])
            if drill_slug in seen_drill_slugs:
                raise ValueError(
                    f"duplicate drill slug in module {module_slug!r}: {drill_slug!r}"
                )
            seen_drill_slugs.add(drill_slug)

            if len(drill["why_it_matters"]) > 500:
                raise ValueError(
                    f"drill {drill_slug!r}: why_it_matters exceeds 500 chars"
                )
            if not isinstance(drill["hints"], list):
                raise ValueError(f"drill {drill_slug!r}: hints must be a list")
            if not isinstance(drill["skill_tags"], list):
                raise ValueError(f"drill {drill_slug!r}: skill_tags must be a list")
            if not isinstance(drill["time_budget_min"], int):
                raise ValueError(f"drill {drill_slug!r}: time_budget_min must be int")
            layer = drill["difficulty_layer"]
            if not isinstance(layer, int) or layer not in (1, 2, 3):
                raise ValueError(
                    f"drill {drill_slug!r}: difficulty_layer must be 1/2/3"
                )


# ── Reference-solution gate ─────────────────────────────────────────


async def _validate_at_load(
    starter_code: str, reference_solution: str, hidden_tests: str
) -> None:
    """Run the YAML's reference solution against its hidden tests.

    Any compiled course YAML must ship an answer key that passes its own
    tests — otherwise the content is broken and we'd surface it to a
    learner as an unsolvable drill. We run this at load time only; the
    result of the canonical solution is thrown away after the check.

    ``starter_code`` is unused in the validation but accepted in the
    signature so future checks (e.g. "starter compiles cleanly" or
    "starter fails the tests as expected") slot in without a service
    rewrite.

    Raises ``ValueError`` with the runner's truncated output on
    mismatch so the error message identifies the actual assertion that
    failed, not just "canonical solution did not pass".
    """

    # Local import to avoid a module-level cycle — drill_runner imports
    # dataclasses/subprocess only, but we keep it symmetric with the
    # router/service style elsewhere.
    from services.drill_runner import run_drill

    _ = starter_code  # reserved for future "starter must fail" checks
    # 30s validation timeout — pytest cold-start in the container can be
    # 8-18s before the test itself runs (CPython + pytest collection +
    # plugin import). 10s was too tight; trivial drills timed out at
    # bootstrap. 30s leaves headroom for any reasonable canonical solution
    # while still flagging genuine infinite-loop refsols. Runtime drill
    # submission stays at the runner's default (no caller bump).
    result = await run_drill(reference_solution, hidden_tests, timeout_s=30.0)
    if not result.passed:
        raise ValueError(
            "reference_solution does not pass its own hidden_tests — "
            f"runner output:\n{result.output}"
        )


# ── Upsert helpers ──────────────────────────────────────────────────


async def _upsert_course(db: AsyncSession, doc: dict[str, Any]) -> DrillCourse:
    """Upsert the course row keyed by slug."""

    stmt = select(DrillCourse).where(DrillCourse.slug == doc["slug"])
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        course = DrillCourse(
            slug=doc["slug"],
            title=doc["title"],
            source=doc["source"],
            version=doc["version"],
            description=doc.get("description"),
            estimated_hours=doc.get("estimated_hours"),
        )
        db.add(course)
        await db.flush()
        return course

    existing.title = doc["title"]
    existing.source = doc["source"]
    existing.version = doc["version"]
    existing.description = doc.get("description")
    existing.estimated_hours = doc.get("estimated_hours")
    await db.flush()
    return existing


async def _upsert_module(
    db: AsyncSession, course_id: Any, module_doc: dict[str, Any]
) -> DrillModule:
    """Upsert a module row keyed by ``(course_id, slug)``."""

    stmt = select(DrillModule).where(
        DrillModule.course_id == course_id,
        DrillModule.slug == module_doc["slug"],
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        module = DrillModule(
            course_id=course_id,
            slug=module_doc["slug"],
            title=module_doc["title"],
            order_index=module_doc["order_index"],
            outcome=module_doc.get("outcome"),
        )
        db.add(module)
        await db.flush()
        return module

    existing.title = module_doc["title"]
    existing.order_index = module_doc["order_index"]
    existing.outcome = module_doc.get("outcome")
    await db.flush()
    return existing


async def _upsert_drill(
    db: AsyncSession, module_id: Any, drill_doc: dict[str, Any]
) -> Drill:
    """Upsert a drill row keyed by ``(module_id, slug)``.

    ``reference_solution`` from the YAML is intentionally NOT persisted
    — the column doesn't exist (critic C3). It was already validated
    in-memory before this call.
    """

    stmt = select(Drill).where(
        Drill.module_id == module_id,
        Drill.slug == drill_doc["slug"],
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    fields = dict(
        title=drill_doc["title"],
        why_it_matters=drill_doc["why_it_matters"],
        starter_code=drill_doc["starter_code"],
        hidden_tests=drill_doc["hidden_tests"],
        hints=list(drill_doc["hints"]),
        skill_tags=list(drill_doc["skill_tags"]),
        source_citation=drill_doc["source_citation"],
        time_budget_min=int(drill_doc["time_budget_min"]),
        difficulty_layer=int(drill_doc["difficulty_layer"]),
        order_index=int(drill_doc.get("order_index", 0)),
    )
    if existing is None:
        drill = Drill(module_id=module_id, slug=drill_doc["slug"], **fields)
        db.add(drill)
        await db.flush()
        return drill

    for key, value in fields.items():
        setattr(existing, key, value)
    await db.flush()
    return existing


# ── Public entry point ──────────────────────────────────────────────


async def load_course(
    db: AsyncSession, course_slug: str, version: str = "v1.0.0"
) -> DrillCourse:
    """Load compiled YAML → upsert into the drill tables → return the course row.

    Args:
        db: Active ``AsyncSession`` — caller owns commit/rollback.
        course_slug: The slug of the course to load (e.g. ``"py4e"``).
        version: Content version subdirectory (default ``"v1.0.0"``).

    Raises:
        FileNotFoundError: the YAML path does not exist anywhere on the
            walk-up search from this module.
        ValueError: schema validation or reference-solution validation
            failed — see :func:`_validate_yaml` and
            :func:`_validate_at_load`.

    Returns:
        The :class:`DrillCourse` row (freshly inserted or updated).
    """

    yaml_path = _locate_course_yaml(course_slug, version)
    if yaml_path is None:
        raise FileNotFoundError(
            f"compiled drill course not found: "
            f"content/drills/{course_slug}/{version}/course.yaml "
            f"(searched up 8 levels from {__file__})"
        )

    with yaml_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    _validate_yaml(data)

    # Validate every drill's reference solution BEFORE touching the DB
    # so a broken YAML aborts cleanly without partial writes. Each
    # subprocess call costs a few hundred ms — acceptable for a seed
    # script; not in the request path.
    for module in data["modules"]:
        for drill in module["drills"]:
            try:
                await _validate_at_load(
                    drill["starter_code"],
                    drill["reference_solution"],
                    drill["hidden_tests"],
                )
            except ValueError as exc:
                raise ValueError(
                    f"drill {drill['slug']!r} in module {module['slug']!r}: {exc}"
                ) from exc

    course = await _upsert_course(db, data)
    for module_doc in data["modules"]:
        module = await _upsert_module(db, course.id, module_doc)
        for drill_doc in module_doc["drills"]:
            await _upsert_drill(db, module.id, drill_doc)

    # Eagerly hydrate ``course.modules`` (and each module's ``drills``)
    # before returning so callers can access the relationship in plain
    # async code without triggering a lazy SQL load. Without this the
    # seed script — which counts ``len(course.modules)`` after this
    # function returns — hits MissingGreenlet because the lazy SELECT
    # is no longer inside an awaited DB call. Selectin-style refresh
    # is safe for SQLite + Postgres parity.
    await db.refresh(course, attribute_names=["modules"])
    for module in course.modules:
        await db.refresh(module, attribute_names=["drills"])

    # Note: caller (seed script / test) is responsible for commit. Load
    # behaves like a bulk-upsert helper, not a self-contained side
    # effect — this matches the shape of
    # ``scripts.seed_python_paths.main``.
    return course


__all__ = [
    "load_course",
]
