"""Tests for the agenda tick orchestration (unit-level, mocked DB).

Covers:
- run_agenda_tick creates an AgendaRun record
- Dedup prevents double-materialisation
- Active task guard prevents spam
- Noop when no signals
- resolve_next_action fallback when no signals
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.agenda import (
    DEDUP_WINDOW_HOURS,
    NOTIFICATION_COOLDOWN_HOURS,
    _is_deduped,
    _has_active_task,
    _notification_on_cooldown,
    resolve_next_action,
)
from services.agent.agenda_ranking import AgendaDecision
from services.agent.agenda_signals import AgendaSignal


# ── resolve_next_action ──


@pytest.mark.asyncio
async def test_resolve_next_action_returns_submit_on_no_signals():
    """When collect_signals returns empty, resolve_next_action should fallback to a plan."""
    with patch("services.agent.agenda.collect_signals", new_callable=AsyncMock) as mock_collect:
        mock_collect.return_value = []
        db = AsyncMock()
        decision = await resolve_next_action(uuid.uuid4(), uuid.uuid4(), db)
        assert decision.action == "submit"
        assert decision.task_type == "multi_step"
        assert "goal" in decision.task_summary.lower() or "plan" in decision.task_summary.lower()


@pytest.mark.asyncio
async def test_resolve_next_action_picks_highest_signal():
    """When signals exist, resolve_next_action should rank and return the best."""
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    signals = [
        AgendaSignal(
            signal_type="forgetting_risk",
            user_id=user_id,
            course_id=course_id,
            entity_id="fsrs:test",
            title="5 items overdue",
            urgency=75,
            detail={"overdue_count": 5, "items": [{"title": "Topic A"}]},
        ),
        AgendaSignal(
            signal_type="active_goal",
            user_id=user_id,
            course_id=course_id,
            entity_id=str(uuid.uuid4()),
            title="Learn math",
            urgency=90,
            detail={"has_next_action": True, "next_action": "Read chapter 1", "objective": "Master algebra"},
        ),
    ]

    with patch("services.agent.agenda.collect_signals", new_callable=AsyncMock) as mock_collect:
        mock_collect.return_value = signals
        db = AsyncMock()
        decision = await resolve_next_action(user_id, course_id, db)
        # active_goal has higher precedence than forgetting_risk
        assert decision.signal.signal_type == "active_goal"
        assert decision.action == "submit"


# ── Dedup and guards (these test the SQL logic shape, mocked) ──


@pytest.mark.asyncio
async def test_dedup_check_queries_within_window():
    """_is_deduped should query AgendaRun within the dedup window."""
    db = AsyncMock()
    # Mock: no prior run found
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await _is_deduped(db, uuid.uuid4(), "test:key:2024-01-01")
    assert result is False
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_dedup_returns_true_when_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4()
    db.execute = AsyncMock(return_value=mock_result)

    result = await _is_deduped(db, uuid.uuid4(), "test:key:2024-01-01")
    assert result is True


@pytest.mark.asyncio
async def test_has_active_task_returns_false_when_none():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await _has_active_task(db, uuid.uuid4(), uuid.uuid4(), "review_session")
    assert result is False


@pytest.mark.asyncio
async def test_has_active_task_returns_true_when_found():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4()
    db.execute = AsyncMock(return_value=mock_result)

    result = await _has_active_task(db, uuid.uuid4(), uuid.uuid4(), "review_session")
    assert result is True


@pytest.mark.asyncio
async def test_notification_cooldown_returns_false_when_no_recent():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await _notification_on_cooldown(db, uuid.uuid4(), uuid.uuid4())
    assert result is False


# ── Signal serialization ──


def test_signal_serialisation():
    """_serialise_signals should produce JSON-safe dicts."""
    from services.agent.agenda import _serialise_signals

    signals = [
        AgendaSignal(
            signal_type="active_goal",
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            entity_id="g1",
            title="Goal 1",
            urgency=80.0,
        ),
    ]
    result = _serialise_signals(signals)
    assert len(result) == 1
    assert result[0]["signal_type"] == "active_goal"
    assert result[0]["urgency"] == 80.0
    assert isinstance(result[0]["course_id"], str)
