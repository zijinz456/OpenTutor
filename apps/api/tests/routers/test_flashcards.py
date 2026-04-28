"""Regression test for BUG-FSRS-001 — `/api/flashcards/review` persistence.

Contract under test: a successful flashcard review POST must persist the
new FSRS state to ``generated_assets.content`` AND bump ``updated_at``.

The bug: ``models/compat.py`` aliases ``CompatJSONB = JSON`` (without
``MutableDict.as_mutable``). The handler in ``routers/flashcards.py``
mutates ``asset.content`` via a dict spread that shares inner refs with
the original — SQLAlchemy's history reports empty ``added``/``deleted``
and silently skips the UPDATE on commit. The fix is an explicit
``flag_modified(asset, "content")`` after the mutation.

Without the fix, the asserts below fail: ``cards[0].fsrs.reps`` stays at
0, ``state`` stays at ``"new"``, and ``updated_at`` stays at the
``server_default`` insert timestamp — the smoking-gun signature of the
silent persistence loss surfaced by ``docs/qa/practice_results_write_
rate_audit_2026_04_27.md``.

Harness mirrors ``tests/routers/test_quiz_submission.py`` — in-memory
SQLite with ``StaticPool`` plus direct handler invocation, so we exercise
the real SA session/commit path without spinning up the ASGI auth layer
or any external services.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.generated_asset import GeneratedAsset
from models.user import User


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite per test (``StaticPool`` keeps it alive)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session_factory):
    """Seed user + course + a flashcard ``GeneratedAsset`` with a single
    card in the FSRS ``new`` state (reps=0, last_review=None).

    Returns ``(user, course_id, batch_id, asset_id)`` so the test can
    drive the ``review_flashcard_endpoint`` and re-fetch the row.
    """
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    card_id = str(uuid.uuid4())

    async with session_factory() as s:
        s.add(User(id=user_id, name="Owner"))
        s.add(Course(id=course_id, name="Python", description="t", user_id=user_id))
        s.add(
            GeneratedAsset(
                id=asset_id,
                user_id=user_id,
                course_id=course_id,
                asset_type="flashcards",
                title="Test batch",
                content={
                    "cards": [
                        {
                            "id": card_id,
                            "front": "What is a Python generator?",
                            "back": "A function using yield to lazily produce values.",
                            "course_id": str(course_id),
                            "fsrs": {
                                "difficulty": 5.0,
                                "stability": 0.0,
                                "reps": 0,
                                "lapses": 0,
                                "state": "new",
                                "last_review": None,
                            },
                        }
                    ]
                },
                metadata_={"count": 1},
                batch_id=batch_id,
                version=1,
                is_archived=False,
            )
        )
        await s.commit()

    async with session_factory() as s:
        user = (await s.execute(sa.select(User).where(User.id == user_id))).scalar_one()
    return user, course_id, batch_id, asset_id, card_id


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_persists_fsrs_state_to_db(session_factory, seeded) -> None:
    """BUG-FSRS-001 regression — a successful review must persist
    ``cards[i].fsrs`` AND bump ``updated_at``.

    Pre-fix: this asserts all fail because the UPDATE is silently
    skipped (CompatJSONB doesn't track in-place mutation; the handler's
    dict spread shares inner refs so SA's history is empty).

    Post-fix: the explicit ``flag_modified(asset, "content")`` in
    ``routers/flashcards.py`` forces SA to mark the column dirty, the
    UPDATE fires, and the assertions pass.
    """
    user, course_id, batch_id, asset_id, card_id = seeded

    # Capture the pre-state ``updated_at`` so we can assert it advanced.
    async with session_factory() as s:
        pre_asset = (
            await s.execute(
                sa.select(GeneratedAsset).where(GeneratedAsset.id == asset_id)
            )
        ).scalar_one()
        pre_updated_at = pre_asset.updated_at
        pre_fsrs = pre_asset.content["cards"][0]["fsrs"]
        assert pre_fsrs["reps"] == 0
        assert pre_fsrs["state"] == "new"
        assert pre_fsrs["last_review"] is None

    # Drive the handler directly. Imported here so any test-time monkey-
    # patches (none currently, but mirrors the quiz_submission pattern)
    # apply before the router's late imports resolve.
    from routers.flashcards import ReviewRequest, review_flashcard_endpoint

    body = ReviewRequest(
        card={
            "id": card_id,
            "front": "What is a Python generator?",
            "back": "A function using yield to lazily produce values.",
            "course_id": str(course_id),
            "fsrs": {
                "difficulty": 5.0,
                "stability": 0.0,
                "reps": 0,
                "lapses": 0,
                "state": "new",
            },
        },
        rating=4,  # Easy
        batch_id=batch_id,
        card_index=0,
    )

    async with session_factory() as db:
        response = await review_flashcard_endpoint(body=body, user=user, db=db)

    # The handler returned the computed FSRS state in the response; the
    # bug is that this state never made it to the DB. Sanity-check the
    # response shape so we know the handler didn't 500 on us silently.
    assert response["card"]["fsrs"]["reps"] == 1
    assert response["card"]["fsrs"]["state"] == "review"

    # The contract: re-fetching the asset MUST show the new FSRS state
    # AND a bumped ``updated_at``. These asserts are the smoking gun.
    async with session_factory() as s:
        post_asset = (
            await s.execute(
                sa.select(GeneratedAsset).where(GeneratedAsset.id == asset_id)
            )
        ).scalar_one()
        post_fsrs = post_asset.content["cards"][0]["fsrs"]

        assert post_fsrs["reps"] == 1, (
            "FSRS reps did not persist — flag_modified missing? "
            f"got {post_fsrs['reps']}, expected 1"
        )
        assert post_fsrs["state"] == "review", (
            "FSRS state did not persist — got "
            f"{post_fsrs['state']!r}, expected 'review'"
        )
        assert post_fsrs["last_review"] is not None, (
            "FSRS last_review did not persist (still None)"
        )
        assert post_asset.updated_at > pre_updated_at, (
            "GeneratedAsset.updated_at did not advance — UPDATE was skipped"
        )
