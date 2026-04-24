"""Seed compiled drill courses from ``content/drills/*/v1.0.0/course.yaml``.

Phase 16c practice-first pivot — this is the one-shot bootstrap that
turns Codex's build-time YAML (compiled by ``transpile_drills.py``)
into DB rows the router and UI can serve. Idempotent via
``drill_loader`` slug upserts; rerun after ``transpile_drills.py``
refreshes content.

Usage
-----

    python apps/api/scripts/seed_drill_courses.py [--course-slug py4e]
                                                  [--dry-run]
                                                  [--skip-broken]

* ``--course-slug SLUG``: seed only one course (default: all discovered).
* ``--dry-run``: validate + print what *would* upsert, then roll back.
* ``--skip-broken``: drop drills whose ``reference_solution`` contains
  ``TODO`` or is empty *before* running the reference-solution gate. The
  default is strict — a broken drill aborts the course. Opt-in lax mode
  lets the 140 good drills land while Codex/author is still filling in
  the last 9 placeholders.

Why a separate runner (and not app_lifecycle's auto-seed)?
----------------------------------------------------------

``_validate_at_load`` spawns a subprocess per drill to run the canonical
solution through the sandbox — that's ~150 drills × ~400ms = a full
minute. We do NOT want that on every API boot. Seed is a manual
operation after a content change, not a startup cost.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import async_session  # noqa: E402
from services import drill_loader  # noqa: E402


# ── Discovery ────────────────────────────────────────────────────────


def _locate_content_root() -> Path | None:
    """Walk up from this file looking for ``content/drills/``.

    Mirrors ``drill_loader._locate_course_yaml``'s 8-level walk so the
    seed works from the container (/app/apps/api/scripts) and from a
    local checkout (repo root with content/ at top level).
    """

    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current / "content" / "drills"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _discover_courses(drills_root: Path) -> list[tuple[str, str]]:
    """Return ``[(slug, version), ...]`` for every compiled course.yaml.

    Expects ``content/drills/{slug}/v{version}/course.yaml``. A course
    with multiple version dirs produces multiple tuples — the seed
    upserts each in order, but in practice only the latest is kept on
    disk. Sorted by slug so output is deterministic.
    """

    found: list[tuple[str, str]] = []
    for course_dir in sorted(p for p in drills_root.iterdir() if p.is_dir()):
        for version_dir in sorted(
            p for p in course_dir.iterdir() if p.is_dir() and p.name.startswith("v")
        ):
            yaml_path = version_dir / "course.yaml"
            if yaml_path.is_file():
                found.append((course_dir.name, version_dir.name))
    return found


# ── Lax filtering ────────────────────────────────────────────────────


def _drill_is_placeholder(drill: dict[str, Any]) -> bool:
    """True when ``reference_solution`` is empty or contains ``TODO``.

    Authors (humans or Codex) sometimes ship stub refsols. Strict seed
    aborts the whole course on a stub — lax mode drops just the stubs
    and lets the rest land.
    """

    refsol = drill.get("reference_solution")
    if not isinstance(refsol, str) or not refsol.strip():
        return True
    return "TODO" in refsol


def _filter_broken_drills(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Return ``(filtered_doc, dropped)`` where ``dropped`` is a list of
    ``(module_slug, drill_slug)`` pairs that were removed.

    Modules that lose all their drills are also dropped — drill_loader's
    validator requires a non-empty ``drills`` list.
    """

    dropped: list[tuple[str, str]] = []
    kept_modules: list[dict[str, Any]] = []
    for module in data.get("modules", []):
        kept_drills = []
        for drill in module.get("drills", []):
            if _drill_is_placeholder(drill):
                dropped.append((module["slug"], drill["slug"]))
                continue
            kept_drills.append(drill)
        if kept_drills:
            module = {**module, "drills": kept_drills}
            kept_modules.append(module)
    filtered = {**data, "modules": kept_modules}
    return filtered, dropped


# ── Seed one course ──────────────────────────────────────────────────


async def _seed_one(
    db, course_slug: str, version: str, *, skip_broken: bool
) -> dict[str, int]:
    """Upsert a single course. Returns counts + dropped-drill count.

    Strict path (``skip_broken=False``) delegates entirely to
    ``drill_loader.load_course`` — any broken drill aborts the course.
    Lax path filters placeholders in-memory, re-validates, and calls
    drill_loader's internal upsert helpers directly.
    """

    if not skip_broken:
        course = await drill_loader.load_course(db, course_slug, version)
        modules = len(course.modules) if course.modules is not None else 0
        drills = sum(
            len(m.drills) for m in (course.modules or []) if m.drills is not None
        )
        return {"courses": 1, "modules": modules, "drills": drills, "dropped": 0}

    yaml_path = drill_loader._locate_course_yaml(course_slug, version)
    if yaml_path is None:
        raise FileNotFoundError(
            f"compiled drill course not found: content/drills/"
            f"{course_slug}/{version}/course.yaml"
        )
    with yaml_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    drill_loader._validate_yaml(data)

    filtered, dropped = _filter_broken_drills(data)
    if not filtered["modules"]:
        raise ValueError(
            f"course {course_slug!r}: all modules lost every drill to the "
            f"placeholder filter — nothing to seed"
        )

    # Second-pass filter: the placeholder check only catches refsols that
    # SAY they're broken. Some drills pass the syntax check but still
    # fail the subprocess gate — e.g. an interactive drill whose refsol
    # calls ``input()`` and times out in the sandbox. Lax mode drops
    # those too, logging each one so the author can see what to fix.
    surviving_modules: list[dict[str, Any]] = []
    for module in filtered["modules"]:
        kept: list[dict[str, Any]] = []
        for drill in module["drills"]:
            try:
                await drill_loader._validate_at_load(
                    drill["starter_code"],
                    drill["reference_solution"],
                    drill["hidden_tests"],
                )
            except ValueError as exc:
                dropped.append((module["slug"], drill["slug"]))
                print(
                    f"  skip {module['slug']}/{drill['slug']}: "
                    f"{str(exc).splitlines()[0][:120]}"
                )
                continue
            kept.append(drill)
        if kept:
            surviving_modules.append({**module, "drills": kept})
    filtered = {**filtered, "modules": surviving_modules}
    if not filtered["modules"]:
        raise ValueError(
            f"course {course_slug!r}: all drills failed the reference-solution "
            f"gate — nothing to seed"
        )
    drill_loader._validate_yaml(filtered)

    course = await drill_loader._upsert_course(db, filtered)
    module_count = 0
    drill_count = 0
    for module_doc in filtered["modules"]:
        module = await drill_loader._upsert_module(db, course.id, module_doc)
        module_count += 1
        for drill_doc in module_doc["drills"]:
            await drill_loader._upsert_drill(db, module.id, drill_doc)
            drill_count += 1

    return {
        "courses": 1,
        "modules": module_count,
        "drills": drill_count,
        "dropped": len(dropped),
    }


# ── Entry point ──────────────────────────────────────────────────────


async def main(
    *,
    course_slug_filter: str | None = None,
    dry_run: bool = False,
    skip_broken: bool = False,
    session_factory=async_session,
) -> int:
    """Discover and seed every compiled drill course.

    Returns exit code: 0 on success, 2 if no content root, 3 if a
    specific ``course_slug_filter`` had no match.
    """

    drills_root = _locate_content_root()
    if drills_root is None:
        print("ERROR: content/drills/ not found (walked 8 levels up)")
        return 2

    courses = _discover_courses(drills_root)
    if course_slug_filter:
        courses = [(s, v) for s, v in courses if s == course_slug_filter]
        if not courses:
            print(f"ERROR: no compiled course matches slug {course_slug_filter!r}")
            return 3

    print(f"Content root: {drills_root}")
    print(
        f"Discovered {len(courses)} course(s): "
        f"{', '.join(f'{s}@{v}' for s, v in courses) or '(none)'}"
    )

    totals = {"courses": 0, "modules": 0, "drills": 0, "dropped": 0}
    failures: list[tuple[str, str]] = []

    async with session_factory() as db:
        for slug, version in courses:
            print(f"\n-> seeding {slug} {version} ...")
            try:
                counts = await _seed_one(db, slug, version, skip_broken=skip_broken)
            except (FileNotFoundError, ValueError) as exc:
                print(f"  FAIL: {exc}")
                failures.append((slug, str(exc)))
                continue
            for key, value in counts.items():
                totals[key] += value
            print(
                f"  ok - modules={counts['modules']} drills={counts['drills']}"
                + (
                    f" (dropped {counts['dropped']} placeholders)"
                    if counts["dropped"]
                    else ""
                )
            )

        if dry_run:
            await db.rollback()
            suffix = " [ROLLED BACK]"
        else:
            await db.commit()
            suffix = ""

    print(
        f"\nTotals{suffix}: courses={totals['courses']} modules={totals['modules']} "
        f"drills={totals['drills']} dropped={totals['dropped']}"
    )
    if failures:
        print(f"\n{len(failures)} course(s) failed:")
        for slug, err in failures:
            print(f"  - {slug}: {err[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n", 1)[0].strip(),
    )
    parser.add_argument("--course-slug", default=None, help="seed only this slug")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + print plan, roll back the transaction",
    )
    parser.add_argument(
        "--skip-broken",
        action="store_true",
        help="drop drills with TODO/empty reference_solution instead of aborting",
    )
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            main(
                course_slug_filter=args.course_slug,
                dry_run=args.dry_run,
                skip_broken=args.skip_broken,
            )
        )
    )
