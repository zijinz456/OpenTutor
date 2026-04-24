"""Seed Learning Paths from ``content/python_full_curriculum.yaml``.

Creates one ``LearningPath`` row per yaml track (4 paths:
python-fundamentals / python-intermediate / python-advanced /
python-practical) + one ``PathRoom`` per yaml module (~38 rooms across
the four tracks), then back-fills ``path_room_id`` and ``task_order``
on existing ``practice_problems`` by matching each problem's parent
``CourseContentTree.source_file`` URL against each module's curated
source URLs from the yaml.

Idempotent on re-run: paths are upserted by ``slug`` and rooms by
``(path_id, slug)``. Card-to-room mapping is deterministic because the
URL-match key is normalized (lowercase host + path, query/fragment/
trailing-slash stripped) and we only consider problems whose
``path_room_id`` is still ``NULL`` — already-mapped cards are left
alone so running the seed twice never reshuffles existing
assignments.

Usage::

    python apps/api/scripts/seed_python_paths.py [--dry-run]

``--dry-run`` reports what *would* happen and rolls back. The non-dry
path prints the same per-module report and commits.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# apps/api is the import root for the app when invoked outside the
# container; the tests add it to sys.path via conftest, but running
# this script directly (``python apps/api/scripts/seed_python_paths.py``)
# needs the same treatment.
_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import async_session  # noqa: E402
from models.content import CourseContentTree  # noqa: E402
from models.learning_path import LearningPath, PathRoom  # noqa: E402
from models.practice import PracticeProblem  # noqa: E402

_DEFAULT_OUTCOME = "Complete this mission"
_DEFAULT_DIFFICULTY = 2
_DEFAULT_ETA_MINUTES = 15
_DEFAULT_MODULE_LABEL = ""


# ── URL normalization ──────────────────────────────────────────────────


def _url_match_key(url: str) -> str:
    """Return a comparable key for ``url``: lowercase host + path.

    Kept for URL deduplication inside the yaml loader. NOT used for the
    card→room mapping — see ``_url_to_title_hints`` for that.
    """

    parts = urlsplit(url.strip().lower())
    path = parts.path.rstrip("/")
    return f"{parts.netloc}{path}"


def _url_to_title_hints(url: str) -> set[str]:
    """Extract substring tokens from a URL that should appear in the
    scraped page's ``<title>`` element.

    The ingestion pipeline stores the page title in
    ``CourseContentTree.source_file`` (not the URL itself — a repo
    quirk). So to map a yaml-curated URL to the rows it produced, we
    pull likely keyword stems from the URL slug and substring-match
    them against the title.

    Example::

        "https://realpython.com/defining-your-own-python-function/"
        → {"defining your own python function"}

        "https://docs.python.org/3/tutorial/introduction.html"
        → {"introduction"}

        "https://docs.python.org/3/tutorial/controlflow.html"
        → {"controlflow", "control flow"}

        "https://peps.python.org/pep-0589/"
        → {"pep-0589", "pep 0589", "pep 589"}
    """

    parts = urlsplit(url.strip().lower())
    # Last non-empty path segment, stripped of extension.
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return set()
    last = segments[-1]
    last = re.sub(r"\.(html?|md|pdf)$", "", last)
    hints: set[str] = {last}

    # Kebab → space variant for multi-word slugs.
    if "-" in last:
        hints.add(last.replace("-", " "))

    # PEP-style: "pep-0589" → "pep 589" (strip leading zero from number).
    m = re.match(r"^pep[-_]0*(\d+)$", last)
    if m:
        hints.add(f"pep {m.group(1)}")

    # Python tutorial numbered sections don't include the number in the URL
    # slug, but the title does ("3. An Informal Introduction"). Add the
    # whole-word slug as a hint; the number prefix on the title doesn't
    # break substring match.
    return hints


def _matches_any_hint(title: str, hints: set[str]) -> bool:
    """Case-insensitive substring match: any hint present → match."""

    if not title or not hints:
        return False
    lower = title.lower()
    return any(h in lower for h in hints if h)


# ── Upserts ────────────────────────────────────────────────────────────


async def _upsert_path(
    db: AsyncSession,
    *,
    slug: str,
    title: str,
    difficulty: str,
    track_id: str,
    description: str | None,
    room_count_target: int,
) -> LearningPath:
    """Upsert a ``LearningPath`` keyed by globally-unique ``slug``."""

    existing = (
        await db.execute(select(LearningPath).where(LearningPath.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        existing.title = title
        existing.difficulty = difficulty
        existing.track_id = track_id
        existing.description = description
        existing.room_count_target = room_count_target
        await db.flush()
        return existing
    row = LearningPath(
        id=uuid4(),
        slug=slug,
        title=title,
        difficulty=difficulty,
        track_id=track_id,
        description=description,
        room_count_target=room_count_target,
    )
    db.add(row)
    await db.flush()
    return row


async def _upsert_room(
    db: AsyncSession,
    *,
    path_id,
    slug: str,
    title: str,
    room_order: int,
    intro_excerpt: str | None,
    task_count_target: int,
    outcome: str = _DEFAULT_OUTCOME,
    difficulty: int = _DEFAULT_DIFFICULTY,
    eta_minutes: int = _DEFAULT_ETA_MINUTES,
    module_label: str = _DEFAULT_MODULE_LABEL,
) -> PathRoom:
    """Upsert a ``PathRoom`` keyed by ``(path_id, slug)``."""

    existing = (
        await db.execute(
            select(PathRoom).where(
                PathRoom.path_id == path_id,
                PathRoom.slug == slug,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.title = title
        existing.room_order = room_order
        existing.intro_excerpt = intro_excerpt
        existing.task_count_target = task_count_target
        existing.outcome = outcome
        existing.difficulty = difficulty
        existing.eta_minutes = eta_minutes
        existing.module_label = module_label
        await db.flush()
        return existing
    row = PathRoom(
        id=uuid4(),
        path_id=path_id,
        slug=slug,
        title=title,
        room_order=room_order,
        intro_excerpt=intro_excerpt,
        outcome=outcome,
        difficulty=difficulty,
        eta_minutes=eta_minutes,
        module_label=module_label,
        task_count_target=task_count_target,
    )
    db.add(row)
    await db.flush()
    return row


# ── Card → room mapping ────────────────────────────────────────────────


async def _map_cards_to_room(
    db: AsyncSession,
    *,
    room_id,
    module_url_keys: set[str],
    module_title_hints: set[str] | None = None,
) -> int:
    """Assign ``path_room_id`` on every orphan problem whose parent
    content-tree node's ``source_file`` matches one of ``module_url_keys``.

    Returns the count of rows updated. ``task_order`` is assigned in
    the order rows come back (id-stable within a transaction — good
    enough for a seed; T3 endpoints order by ``task_order`` then
    ``order_index`` then id, so ties are still deterministic later).

    Only problems with ``path_room_id IS NULL`` are considered —
    already-mapped problems are idempotently skipped so a re-run never
    reshuffles existing assignments.
    """

    if not module_url_keys:
        return 0

    # Join problems → content_tree so we can read ``source_file``
    # without a separate round-trip per row. Filter to problems that
    # don't already belong to a room.
    rows = (
        await db.execute(
            select(PracticeProblem, CourseContentTree.source_file)
            .join(
                CourseContentTree,
                PracticeProblem.content_node_id == CourseContentTree.id,
            )
            .where(
                PracticeProblem.path_room_id.is_(None),
                CourseContentTree.source_file.is_not(None),
            )
        )
    ).all()

    updated = 0
    task_order = 0
    hints = module_title_hints or set()
    for problem, source_file in rows:
        if not source_file:
            continue
        # source_file may be the raw URL (legacy ingests) OR the scraped
        # page title (current pipeline). Try URL-key first; fall back to
        # title-hint substring match.
        matched = _url_match_key(source_file) in module_url_keys or _matches_any_hint(
            source_file, hints
        )
        if matched:
            problem.path_room_id = room_id
            problem.task_order = task_order
            task_order += 1
            updated += 1
    return updated


# ── Curriculum loader ──────────────────────────────────────────────────


def _locate_curriculum_yaml() -> Path | None:
    """Walk up from ``__file__`` looking for ``content/python_full_curriculum.yaml``.

    Mirrors ``interviewer_prompts._resolve_content_dir`` — no env var
    override needed here because the seed is a one-shot script.
    Returns ``None`` if not found so the caller can emit a clear error.
    """

    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current / "content" / "python_full_curriculum.yaml"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


# ── Entry point ────────────────────────────────────────────────────────


async def main(
    dry_run: bool = False,
    *,
    yaml_path_override: Path | None = None,
    session_factory=async_session,
) -> int:
    """Seed paths + rooms + card mappings from the curriculum yaml.

    ``yaml_path_override`` is a test-only hook so unit tests can feed a
    fixture yaml without monkeypatching the filesystem walk.
    ``session_factory`` is injected for the same reason — tests swap
    in a SQLite async sessionmaker.

    Returns an exit code: 0 success, 2 curriculum yaml missing.
    """

    yaml_path = yaml_path_override or _locate_curriculum_yaml()
    if yaml_path is None or not yaml_path.is_file():
        print("ERROR: python_full_curriculum.yaml not found (walked 8 levels up)")
        return 2
    print(f"Reading curriculum from: {yaml_path}")

    with yaml_path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}

    async with session_factory() as db:
        total_paths = 0
        total_rooms = 0
        total_mapped = 0

        for track in doc.get("tracks", []) or []:
            track_id = track.get("id") or "unknown_track"
            modules = track.get("modules", []) or []
            path = await _upsert_path(
                db,
                # Hyphen slug for URL friendliness: ``python_fundamentals``
                # in the yaml → ``python-fundamentals`` in the URL.
                slug=track_id.replace("_", "-"),
                title=track.get("title", track_id),
                difficulty=track.get("difficulty", "intermediate"),
                track_id=track_id,
                description=track.get("why"),
                room_count_target=len(modules),
            )
            total_paths += 1

            for idx, module in enumerate(modules):
                module_id = module.get("id") or f"module_{idx}"
                module_title = module.get("title", module_id)
                sources = module.get("sources", []) or []
                url_keys = {
                    _url_match_key(src["url"]) for src in sources if src.get("url")
                }
                # Build title-hint set from the same sources — used by the
                # card→room mapper when source_file is a page title
                # (current pipeline) rather than a raw URL.
                title_hints: set[str] = set()
                for src in sources:
                    url = src.get("url")
                    if url:
                        title_hints |= _url_to_title_hints(url)
                # Add the module's yaml title prefix (before first ":" or
                # ",") as a fallback hint — catches cases where the URL
                # slug is a single fused word ("controlflow") but the page
                # title uses spaces ("Control Flow Tools").
                mtitle_lower = module_title.lower()
                head = re.split(r"[:,()\[\]]", mtitle_lower, maxsplit=1)[0].strip()
                if head and len(head) >= 4:
                    title_hints.add(head)
                # Optional ``match_titles:`` yaml override — explicit
                # substring list for orphans the URL-slug heuristic
                # misses. Added 2026-04-24 after 411 unmapped cards
                # surfaced on Python Basics. Empty / missing → no-op.
                for explicit in module.get("match_titles") or []:
                    if isinstance(explicit, str) and explicit.strip():
                        title_hints.add(explicit.strip().lower())
                cards_target = int(module.get("cards_target", 0) or 0)

                # Placeholder intro — T-later will extract real prose
                # from ``CourseContentTree.content`` once per room. For
                # T2 we only need a seeded string so the UI doesn't
                # crash on a null field.
                intro_placeholder = (
                    f"Topic: {module_title}. Grounded in {len(url_keys)} "
                    f"curated source(s)."
                )

                room = await _upsert_room(
                    db,
                    path_id=path.id,
                    slug=module_id,
                    title=module_title,
                    room_order=idx,
                    intro_excerpt=intro_placeholder,
                    task_count_target=cards_target,
                )
                total_rooms += 1

                mapped = await _map_cards_to_room(
                    db,
                    room_id=room.id,
                    module_url_keys=url_keys,
                    module_title_hints=title_hints,
                )
                total_mapped += mapped
                print(f"  {track_id[:22]:<22} / {module_id:<28} cards mapped +{mapped}")

        if dry_run:
            await db.rollback()
            print(
                f"\n[DRY RUN] Would upsert: {total_paths} paths, "
                f"{total_rooms} rooms, {total_mapped} card mappings. "
                f"Rolled back."
            )
        else:
            await db.commit()
            print(
                f"\nCommitted: {total_paths} paths, {total_rooms} rooms, "
                f"{total_mapped} card→room mappings"
            )

        # Informational orphan count — the dashboard pill caption uses
        # the same number (critic C2) so Юрій sees unmapped cards exist.
        orphans = (
            (
                await db.execute(
                    select(PracticeProblem).where(
                        PracticeProblem.path_room_id.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        print(f"Orphan cards (no path_room_id): {len(orphans)}")

    return 0


if __name__ == "__main__":
    description = (__doc__ or "").split("\n\n", 1)[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen and roll back without committing.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
