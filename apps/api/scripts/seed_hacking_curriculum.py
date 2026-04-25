"""Seed the Hacking Foundations track via the existing URL ingest pipeline.

The script:
1. Loads ``content/hacking/curriculum.yaml``.
2. Upserts one learning path plus 10 path rooms.
3. Runs each curated URL through ``run_ingestion_pipeline()`` inline.
4. Waits for detached card-generation tasks to finish.
5. Reuses ``_map_cards_to_room()`` from ``seed_python_paths.py`` to attach
   generated cards to the right room.
6. Maps any pre-existing Juice Shop ``lab_exercise`` cards into the final room.

Idempotency:
- path upsert by ``learning_paths.slug``
- room upsert by ``(path_id, slug)``
- URL ingest skip by successful ``ingestion_jobs`` rows for the same course
- card-to-room mapping only touches orphan cards, so reruns do not reshuffle

Usage::

    python scripts/seed_hacking_curriculum.py --sleep 5 --timeout 240
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from database import async_session  # noqa: E402
from models.course import Course  # noqa: E402
from models.ingestion import IngestionJob  # noqa: E402
from models.learning_path import PathRoom  # noqa: E402
from models.practice import LAB_EXERCISE_TYPE, PracticeProblem  # noqa: E402
from models.user import User  # noqa: E402
from routers.upload_processing import _derive_filename, _normalize_scrape_url  # noqa: E402
from scripts.path_capstones import backfill_room_capstones  # noqa: E402
from scripts.seed_python_paths import (  # noqa: E402
    _map_cards_to_room,
    _upsert_path,
    _upsert_room,
    _url_match_key,
    _url_to_title_hints,
)
from services.agent.background_runtime import wait_for_background_tasks  # noqa: E402
from services.ingestion.pipeline import run_ingestion_pipeline  # noqa: E402

DEFAULT_SLEEP_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 240.0
DEFAULT_FAILURE_TOLERANCE = 5

CURRICULUM_SUBPATH = Path("content") / "hacking" / "curriculum.yaml"
PYTHON_CURRICULUM_SUBPATH = Path("content") / "python_full_curriculum.yaml"
COURSE_NAME = "Hacking Foundations"
COURSE_METADATA = {"seed_slug": "hacking-foundations", "track": "hacking"}
OUTCOME_GUARDS = (
    "against juice shop on :3100 only",
    "systems you have permission to test",
)

IngestUrlFunc = Callable[
    [AsyncSession, uuid.UUID, uuid.UUID, str, float],
    Awaitable[IngestionJob],
]


def _walk_up_for_file(*relative_parts: str) -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current.joinpath(*relative_parts)
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def _locate_curriculum_yaml() -> Path | None:
    return _walk_up_for_file(*CURRICULUM_SUBPATH.parts)


def _locate_python_curriculum_yaml() -> Path | None:
    return _walk_up_for_file(*PYTHON_CURRICULUM_SUBPATH.parts)


def _load_python_url_keys() -> set[str]:
    python_yaml = _locate_python_curriculum_yaml()
    if python_yaml is None:
        return set()

    with python_yaml.open(encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}

    keys: set[str] = set()
    for track in doc.get("tracks", []) or []:
        for module in track.get("modules", []) or []:
            for source in module.get("sources", []) or []:
                url = source.get("url")
                if isinstance(url, str) and url.strip():
                    keys.add(_url_match_key(url))
    return keys


def _validate_outcome(outcome: str, *, module_slug: str) -> None:
    lower = outcome.strip().lower()
    if not any(guard in lower for guard in OUTCOME_GUARDS):
        raise ValueError(
            f"Module '{module_slug}' outcome must mention either "
            "'against Juice Shop on :3100 only' or "
            "'systems you have permission to test'."
        )


def _load_curriculum(yaml_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with yaml_path.open(encoding="utf-8") as handle:
        doc = yaml.safe_load(handle) or {}

    path_doc = doc.get("path")
    modules = doc.get("modules")
    if not isinstance(path_doc, dict):
        raise ValueError("curriculum.yaml must define a top-level 'path' object")
    if not isinstance(modules, list):
        raise ValueError("curriculum.yaml must define a top-level 'modules' list")
    if path_doc.get("slug") != "hacking-foundations":
        raise ValueError("path.slug must be 'hacking-foundations'")
    if len(modules) != 10:
        raise ValueError(f"Expected 10 modules, found {len(modules)}")

    python_url_keys = _load_python_url_keys()
    seen_module_slugs: set[str] = set()
    seen_urls: set[str] = set()

    for module in modules:
        if not isinstance(module, dict):
            raise ValueError("Every module must be a mapping")

        slug = module.get("slug")
        urls = module.get("urls")
        outcome = module.get("outcome")
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("Every module needs a non-empty slug")
        if slug in seen_module_slugs:
            raise ValueError(f"Duplicate module slug: {slug}")
        seen_module_slugs.add(slug)

        if not isinstance(urls, list) or not urls:
            raise ValueError(f"Module '{slug}' needs a non-empty urls list")
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError(f"Module '{slug}' needs a non-empty outcome")
        _validate_outcome(outcome, module_slug=slug)

        for raw_url in urls:
            if not isinstance(raw_url, str) or not raw_url.strip():
                raise ValueError(f"Module '{slug}' contains an empty URL")
            url_key = _url_match_key(raw_url)
            if url_key in seen_urls:
                raise ValueError(f"Duplicate URL in hacking curriculum: {raw_url}")
            if url_key in python_url_keys:
                raise ValueError(
                    f"Hacking curriculum URL overlaps Python curriculum: {raw_url}"
                )
            seen_urls.add(url_key)

    return path_doc, modules


async def _ensure_user(db: AsyncSession) -> User:
    user = (
        await db.execute(select(User).order_by(User.created_at.asc()).limit(1))
    ).scalar_one_or_none()
    if user is not None:
        return user

    user = User(id=uuid.uuid4(), name="Local User")
    db.add(user)
    await db.flush()
    return user


async def _ensure_course(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    description: str | None,
) -> Course:
    course = (
        await db.execute(select(Course).where(Course.name == COURSE_NAME))
    ).scalar_one_or_none()
    if course is None:
        course = Course(
            id=uuid.uuid4(),
            user_id=user_id,
            name=COURSE_NAME,
            description=description,
            metadata_=COURSE_METADATA,
        )
        db.add(course)
        await db.flush()
        return course

    course.description = description
    metadata_payload = dict(course.metadata_ or {})
    metadata_payload.update(COURSE_METADATA)
    course.metadata_ = metadata_payload
    await db.flush()
    return course


async def _cleanup_legacy_handcrafted_cards(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
) -> int:
    rows = (
        (
            await db.execute(
                select(PracticeProblem).where(PracticeProblem.course_id == course_id)
            )
        )
        .scalars()
        .all()
    )

    deleted = 0
    for problem in rows:
        metadata = problem.problem_metadata or {}
        if not isinstance(metadata, dict):
            continue
        if metadata.get("source") != "hand-crafted-mvp":
            continue
        await db.delete(problem)
        deleted += 1
    return deleted


async def _prune_stale_rooms(
    db: AsyncSession,
    *,
    path_id: uuid.UUID,
    keep_slugs: set[str],
) -> int:
    rooms = (
        (await db.execute(select(PathRoom).where(PathRoom.path_id == path_id)))
        .scalars()
        .all()
    )

    deleted = 0
    for room in rooms:
        if room.slug in keep_slugs:
            continue
        problems = (
            (
                await db.execute(
                    select(PracticeProblem).where(
                        PracticeProblem.path_room_id == room.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for problem in problems:
            problem.path_room_id = None
            problem.task_order = None
        await db.delete(room)
        deleted += 1
    return deleted


async def _count_course_cards(db: AsyncSession, *, course_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(PracticeProblem.id)).where(
            PracticeProblem.course_id == course_id
        )
    )
    return int(result.scalar_one() or 0)


async def _count_course_orphans(db: AsyncSession, *, course_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(PracticeProblem.id)).where(
            PracticeProblem.course_id == course_id,
            PracticeProblem.path_room_id.is_(None),
        )
    )
    return int(result.scalar_one() or 0)


async def _count_room_cards(
    db: AsyncSession,
    *,
    room_ids: list[uuid.UUID],
) -> int:
    if not room_ids:
        return 0
    result = await db.execute(
        select(func.count(PracticeProblem.id)).where(
            PracticeProblem.path_room_id.in_(room_ids)
        )
    )
    return int(result.scalar_one() or 0)


async def _reset_course_room_mappings(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
) -> int:
    rows = (
        (
            await db.execute(
                select(PracticeProblem).where(PracticeProblem.course_id == course_id)
            )
        )
        .scalars()
        .all()
    )

    reset = 0
    for problem in rows:
        if problem.path_room_id is None and problem.task_order is None:
            continue
        problem.path_room_id = None
        problem.task_order = None
        reset += 1
    return reset


async def _has_successful_ingestion(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    url: str,
) -> bool:
    normalized_url = _normalize_scrape_url(url)
    existing = (
        await db.execute(
            select(IngestionJob.id).where(
                IngestionJob.course_id == course_id,
                IngestionJob.url == normalized_url,
                IngestionJob.status.in_(("completed", "embedding")),
            )
        )
    ).first()
    return existing is not None


def _module_title_hints(module: dict[str, Any]) -> set[str]:
    hints: set[str] = set()
    for raw_url in module.get("urls", []) or []:
        if isinstance(raw_url, str) and raw_url.strip():
            hints |= _url_to_title_hints(raw_url)

    title = module.get("title")
    if isinstance(title, str) and title.strip():
        lowered = title.strip().lower()
        hints.add(lowered)
        head = re.split(r"[:()/-]", lowered, maxsplit=1)[0].strip()
        if len(head) >= 4:
            hints.add(head)

    for explicit in module.get("match_titles", []) or []:
        if isinstance(explicit, str) and explicit.strip():
            hints.add(explicit.strip().lower())
    return hints


def _mapping_priority(module: dict[str, Any]) -> tuple[int, int, int, str]:
    hints = _module_title_hints(module)
    if not hints:
        return (0, 0, 0, str(module.get("slug") or ""))
    max_words = max(hint.count(" ") + 1 for hint in hints)
    max_len = max(len(hint) for hint in hints)
    total_len = sum(len(hint) for hint in hints)
    return (
        max_words,
        max_len,
        total_len,
        str(module.get("slug") or ""),
    )


async def _ingest_url_inline(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    url: str,
    timeout_seconds: float,
) -> IngestionJob:
    normalized_url = _normalize_scrape_url(url)
    filename = _derive_filename(normalized_url)
    job = await asyncio.wait_for(
        run_ingestion_pipeline(
            db,
            user_id=user_id,
            url=normalized_url,
            filename=filename,
            course_id=course_id,
        ),
        timeout=timeout_seconds,
    )
    if job.status == "failed":
        error_message = job.error_message or f"status={job.status}"
        raise RuntimeError(f"Ingestion failed for {normalized_url}: {error_message}")

    await wait_for_background_tasks(timeout=timeout_seconds)
    await db.rollback()
    refreshed = await db.get(IngestionJob, job.id)
    if refreshed is None:
        raise RuntimeError(f"Ingestion job disappeared for {normalized_url}")
    if refreshed.status == "failed":
        error_message = refreshed.error_message or f"status={refreshed.status}"
        raise RuntimeError(f"Ingestion failed for {normalized_url}: {error_message}")
    return refreshed


def _looks_like_juice_shop_lab(problem: PracticeProblem) -> bool:
    metadata = problem.problem_metadata or {}
    if not isinstance(metadata, dict):
        metadata = {}

    target_url = str(metadata.get("target_url") or "").lower()
    question = (problem.question or "").lower()
    spawn_origin = str(metadata.get("spawn_origin") or "").lower()

    return (
        "localhost:3100" in target_url
        or "juice shop" in question
        or "juice-shop" in question
        or "juice shop" in spawn_origin
        or "juice-shop" in spawn_origin
    )


async def _map_existing_juice_shop_labs(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
) -> int:
    rows = (
        (
            await db.execute(
                select(PracticeProblem)
                .where(
                    PracticeProblem.question_type == LAB_EXERCISE_TYPE,
                    PracticeProblem.path_room_id.is_(None),
                )
                .order_by(PracticeProblem.created_at.asc(), PracticeProblem.id.asc())
            )
        )
        .scalars()
        .all()
    )

    updated = 0
    for problem in rows:
        if not _looks_like_juice_shop_lab(problem):
            continue
        problem.path_room_id = room_id
        problem.task_order = 0
        updated += 1
    return updated


async def _renumber_room_tasks(db: AsyncSession, *, room_id: uuid.UUID) -> int:
    tasks = (
        (
            await db.execute(
                select(PracticeProblem)
                .where(PracticeProblem.path_room_id == room_id)
                .order_by(
                    PracticeProblem.task_order.is_(None),
                    PracticeProblem.task_order.asc(),
                    PracticeProblem.created_at.asc(),
                    PracticeProblem.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    for index, task in enumerate(tasks):
        task.task_order = index
    return len(tasks)


async def main(
    dry_run: bool = False,
    *,
    yaml_path_override: Path | None = None,
    session_factory=async_session,
    ingest_url_func: IngestUrlFunc = _ingest_url_inline,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    failure_tolerance: int = DEFAULT_FAILURE_TOLERANCE,
) -> int:
    yaml_path = yaml_path_override or _locate_curriculum_yaml()
    if yaml_path is None or not yaml_path.is_file():
        print("ERROR: content/hacking/curriculum.yaml not found")
        return 2

    path_doc, modules = _load_curriculum(yaml_path)

    async with session_factory() as db:
        user = await _ensure_user(db)
        course = await _ensure_course(
            db,
            user_id=user.id,
            description=path_doc.get("description"),
        )
        cards_before = await _count_course_cards(db, course_id=course.id)

        path = await _upsert_path(
            db,
            slug=path_doc["slug"],
            title=path_doc["title"],
            difficulty=path_doc["difficulty"],
            track_id=path_doc["track_id"],
            description=path_doc.get("description"),
            room_count_target=len(modules),
        )

        legacy_cards_deleted = await _cleanup_legacy_handcrafted_cards(
            db,
            course_id=course.id,
        )
        stale_rooms_deleted = await _prune_stale_rooms(
            db,
            path_id=path.id,
            keep_slugs={str(module["slug"]) for module in modules},
        )

        room_by_slug: dict[str, PathRoom] = {}
        for room_order, module in enumerate(modules):
            room = await _upsert_room(
                db,
                path_id=path.id,
                slug=module["slug"],
                title=module["title"],
                room_order=room_order,
                intro_excerpt=module["outcome"],
                task_count_target=max(len(module.get("urls", []) or []) * 3, 1),
                outcome=module["outcome"],
                difficulty=int(module["difficulty"]),
                eta_minutes=int(module["eta_minutes"]),
                module_label=module["module_label"],
            )
            room_by_slug[module["slug"]] = room

        if dry_run:
            planned_urls = sum(len(module.get("urls", []) or []) for module in modules)
            await db.rollback()
            print(
                f"[DRY RUN] Would upsert 1 path, {len(modules)} rooms, "
                f"and ingest {planned_urls} URLs."
            )
            return 0

        ingested_urls = 0
        skipped_urls = 0
        failures: list[tuple[str, str]] = []

        for module in modules:
            for raw_url in module.get("urls", []) or []:
                normalized_url = _normalize_scrape_url(raw_url)
                if await _has_successful_ingestion(
                    db,
                    course_id=course.id,
                    url=normalized_url,
                ):
                    skipped_urls += 1
                    continue

                try:
                    await ingest_url_func(
                        db,
                        user.id,
                        course.id,
                        normalized_url,
                        timeout_seconds,
                    )
                    ingested_urls += 1
                except Exception as exc:  # noqa: BLE001 - seed must keep going
                    failures.append((normalized_url, str(exc)))
                    print(f"URL failed: {normalized_url} :: {exc}")
                    continue

                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)

        reset_mappings = await _reset_course_room_mappings(db, course_id=course.id)

        mapped_by_urls = 0
        modules_for_mapping = sorted(
            modules,
            key=_mapping_priority,
            reverse=True,
        )
        for module in modules_for_mapping:
            room = room_by_slug[module["slug"]]
            module_url_keys = {
                _url_match_key(url) for url in module.get("urls", []) or []
            }
            mapped_by_urls += await _map_cards_to_room(
                db,
                room_id=room.id,
                module_url_keys=module_url_keys,
                module_title_hints=_module_title_hints(module),
                course_id=course.id,
            )

        juice_room = room_by_slug.get("juice-shop-practice")
        mapped_existing_labs = 0
        if juice_room is not None:
            mapped_existing_labs = await _map_existing_juice_shop_labs(
                db,
                room_id=juice_room.id,
            )

        for room in room_by_slug.values():
            await _renumber_room_tasks(db, room_id=room.id)

        capstone_updates = await backfill_room_capstones(
            db,
            room_ids=[room.id for room in room_by_slug.values()],
        )
        await db.commit()

        cards_after = await _count_course_cards(db, course_id=course.id)
        room_ids = [room.id for room in room_by_slug.values()]
        room_card_total = await _count_room_cards(db, room_ids=room_ids)
        course_orphans = await _count_course_orphans(db, course_id=course.id)
        created_cards = cards_after - cards_before

    print(
        f"{ingested_urls} URLs ingested, {created_cards} cards created, "
        f"{room_card_total} mapped to rooms, {course_orphans} orphans"
    )
    if skipped_urls:
        print(f"{skipped_urls} URLs skipped because they were already ingested")
    if legacy_cards_deleted or stale_rooms_deleted:
        print(
            f"Legacy cleanup: {legacy_cards_deleted} hand-crafted cards removed, "
            f"{stale_rooms_deleted} stale rooms removed"
        )
    if mapped_by_urls or mapped_existing_labs:
        print(
            f"Room mapping: {mapped_by_urls} cards from URL ingests, "
            f"{mapped_existing_labs} existing Juice Shop lab cards"
        )
    if reset_mappings:
        print(f"Reset {reset_mappings} stale room mappings before remap")
    if capstone_updates:
        print(f"Capstones updated for {capstone_updates} room(s)")
    if failures:
        print("URL failures:")
        for url, error in failures:
            print(f"  - {url}: {error}")

    return 0 if len(failures) <= failure_tolerance else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            main(
                dry_run=args.dry_run,
                sleep_seconds=args.sleep,
                timeout_seconds=args.timeout,
            )
        )
    )
