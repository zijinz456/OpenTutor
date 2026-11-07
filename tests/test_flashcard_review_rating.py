"""POST /flashcards/review must only accept the four FSRS grades (1-4).

The endpoint feeds the rating straight into the FSRS scheduler and persists the
resulting card state, so an out-of-range grade used to either corrupt the
stored card (0, 5-21) or raise IndexError (22+, an HTTP 500).
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from database import get_db
from routers.flashcards import router
from services.auth.dependency import get_current_user


@pytest_asyncio.fixture
async def review_client():
    db = AsyncMock()

    async def override_db():
        yield db

    app = FastAPI()
    app.include_router(router, prefix="/flashcards")
    app.dependency_overrides[get_db] = override_db
    user = SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_current_user] = lambda: user

    # Unhandled exceptions become observable HTTP 500s instead of test errors.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, db


def _payload(rating):
    return {"card": {"front": "What is 2 + 2?", "back": "4"}, "rating": rating}


@pytest.mark.asyncio
@pytest.mark.parametrize("rating", [0, 5, -1, 22, 99])
async def test_review_rejects_rating_outside_1_to_4(review_client, rating):
    client, db = review_client

    response = await client.post("/flashcards/review", json=_payload(rating))

    assert response.status_code == 422
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("rating", [1, 2, 3, 4])
async def test_review_accepts_each_valid_rating(review_client, rating):
    client, db = review_client

    response = await client.post("/flashcards/review", json=_payload(rating))

    assert response.status_code == 200
    fsrs = response.json()["card"]["fsrs"]
    assert fsrs["reps"] == 1
    assert fsrs["due"] is not None
    assert fsrs["state"] == ("review" if rating >= 3 else "learning")
    db.commit.assert_awaited_once()
