"""Tests for the Ambient Study Monitor (LLM deliberation layer).

Covers:
- gather_learning_state constructs proper state dict
- llm_deliberate returns parsed decision or None on failure
- execute_ambient_decision handles each action type
- Edge cases: no sessions, no goals, LLM unavailable
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.ambient_monitor import (
    gather_learning_state,
    llm_deliberate,
    execute_ambient_decision,
)
from services.agent.agenda_signals import AgendaSignal


def _make_signal(**kwargs) -> AgendaSignal:
    defaults = dict(
        signal_type="active_goal",
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        entity_id=str(uuid.uuid4()),
        title="Test signal",
        urgency=70.0,
        detail={},
    )
    defaults.update(kwargs)
    return AgendaSignal(**defaults)


# ── gather_learning_state ──


@pytest.mark.asyncio
async def test_gather_learning_state_basic():
    """Should return a dict with expected keys."""
    user_id = uuid.uuid4()
    signals = [_make_signal(user_id=user_id)]
    db = AsyncMock()

    # Mock: no last session
    no_result = MagicMock()
    no_result.scalar_one_or_none.return_value = None
    no_result.scalar.return_value = 0

    # Mock: goals query
    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(side_effect=[no_result, no_result, goals_result])

    state = await gather_learning_state(user_id, signals, db)

    assert "current_hour" in state
    assert "hours_since_last_study" in state
    assert "overdue_review_items" in state
    assert "active_goals" in state
    assert "stalled_goals" in state
    assert "agenda_signals" in state
    assert state["hours_since_last_study"] is None
    assert state["overdue_review_items"] == 0
    assert state["active_goals"] == 0


@pytest.mark.asyncio
async def test_gather_learning_state_with_session():
    """Should compute hours_since_last_study when a session exists."""
    user_id = uuid.uuid4()
    db = AsyncMock()

    # Mock last session: 5 hours ago
    mock_session = MagicMock()
    mock_session.started_at = datetime.now(timezone.utc) - timedelta(hours=5)
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = mock_session

    overdue_result = MagicMock()
    overdue_result.scalar.return_value = 12

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(side_effect=[session_result, overdue_result, goals_result])

    state = await gather_learning_state(user_id, [], db)

    assert state["hours_since_last_study"] is not None
    assert 4.5 < state["hours_since_last_study"] < 5.5
    assert state["overdue_review_items"] == 12


@pytest.mark.asyncio
async def test_gather_learning_state_stalled_goals():
    """Should detect stalled goals (>2 days without update)."""
    user_id = uuid.uuid4()
    db = AsyncMock()

    no_result = MagicMock()
    no_result.scalar_one_or_none.return_value = None
    no_result.scalar.return_value = 0

    # Mock: one stalled goal
    stalled_goal = MagicMock()
    stalled_goal.id = uuid.uuid4()
    stalled_goal.title = "Learn algebra"
    stalled_goal.updated_at = datetime.now(timezone.utc) - timedelta(days=5)

    goals_result = MagicMock()
    goals_result.scalars.return_value.all.return_value = [stalled_goal]

    db.execute = AsyncMock(side_effect=[no_result, no_result, goals_result])

    state = await gather_learning_state(user_id, [], db)

    assert state["active_goals"] == 1
    assert len(state["stalled_goals"]) == 1
    assert state["stalled_goals"][0]["title"] == "Learn algebra"
    assert state["stalled_goals"][0]["days_stalled"] >= 4


# ── llm_deliberate ──


@pytest.mark.asyncio
async def test_llm_deliberate_returns_parsed_json():
    """Should parse valid JSON response from LLM."""
    mock_client = MagicMock()
    mock_client.extract = AsyncMock(return_value=(
        '{"action": "notify", "reason": "student inactive", "message": "Time to study!", "priority": "normal", "target_course_id": null}',
        None,
    ))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        decision = await llm_deliberate({"current_hour": 10})

    assert decision is not None
    assert decision["action"] == "notify"
    assert decision["reason"] == "student inactive"


@pytest.mark.asyncio
async def test_llm_deliberate_handles_markdown_fences():
    """Should strip markdown code fences from LLM response."""
    mock_client = MagicMock()
    mock_client.extract = AsyncMock(return_value=(
        '```json\n{"action": "silent", "reason": "student is on track"}\n```',
        None,
    ))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        decision = await llm_deliberate({})

    assert decision is not None
    assert decision["action"] == "silent"


@pytest.mark.asyncio
async def test_llm_deliberate_returns_none_on_client_unavailable():
    """Should return None when LLM client is not available."""
    with patch("services.llm.router.get_llm_client", side_effect=RuntimeError("No LLM")):
        decision = await llm_deliberate({})

    assert decision is None


@pytest.mark.asyncio
async def test_llm_deliberate_returns_none_on_invalid_json():
    """Should return None when LLM returns non-JSON."""
    mock_client = MagicMock()
    mock_client.extract = AsyncMock(return_value=("This is not JSON!", None))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        decision = await llm_deliberate({})

    assert decision is None


@pytest.mark.asyncio
async def test_llm_deliberate_returns_none_on_missing_action():
    """Should return None when JSON has no 'action' key."""
    mock_client = MagicMock()
    mock_client.extract = AsyncMock(return_value=('{"reason": "test"}', None))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        decision = await llm_deliberate({})

    assert decision is None


# ── execute_ambient_decision ──


@pytest.mark.asyncio
async def test_execute_silent():
    """Silent action should return immediately."""
    status = await execute_ambient_decision(uuid.uuid4(), {"action": "silent"}, AsyncMock())
    assert status == "silent"


@pytest.mark.asyncio
async def test_execute_notify():
    """Notify action should be a no-op (notification system removed)."""
    db = AsyncMock()

    status = await execute_ambient_decision(
        uuid.uuid4(),
        {"action": "notify", "message": "Study now!", "priority": "normal", "target_course_id": None},
        db,
    )

    # Notification system removed — action should still succeed gracefully
    assert status in ("notified", "skipped", "notify_skipped")


@pytest.mark.asyncio
async def test_execute_prepare_review():
    """prepare_review action should submit a review_session task when none active."""
    db = AsyncMock()

    # Mock: no active review task found
    no_active_result = MagicMock()
    no_active_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=no_active_result)

    with patch("services.activity.engine.submit_task", new_callable=AsyncMock) as mock_submit:
        mock_submit.return_value = MagicMock(id=uuid.uuid4())
        status = await execute_ambient_decision(
            uuid.uuid4(),
            {"action": "prepare_review", "reason": "High forgetting risk", "target_course_id": None},
            db,
        )

    assert status == "review_queued"
    mock_submit.assert_called_once()
    call_kwargs = mock_submit.call_args[1]
    assert call_kwargs["task_type"] == "review_session"


@pytest.mark.asyncio
async def test_execute_prepare_review_dedup():
    """prepare_review should skip if a review task is already active."""
    db = AsyncMock()

    # Mock: active review task exists
    active_result = MagicMock()
    active_result.scalar_one_or_none.return_value = uuid.uuid4()
    db.execute = AsyncMock(return_value=active_result)

    status = await execute_ambient_decision(
        uuid.uuid4(),
        {"action": "prepare_review", "reason": "test", "target_course_id": None},
        db,
    )

    assert status == "review_already_queued"


@pytest.mark.asyncio
async def test_execute_unknown_action():
    """Unknown action should return 'unknown_action'."""
    status = await execute_ambient_decision(
        uuid.uuid4(),
        {"action": "dance_party"},
        AsyncMock(),
    )
    assert status == "unknown_action"
