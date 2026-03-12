"""Tests for the scheduler engine.

Covers:
- Schedule configuration and job registration
- _for_each_user helper logic
- _push_notification storage
- Job list completeness
- start_scheduler / stop_scheduler lifecycle
- No-op stubs (timing_analysis, escalation_check)
- Session timing / interval checks

The scheduler engine has deep transitive imports (APScheduler, SQLAlchemy
models, activity engine, etc.).  We mock the heavy dependencies at the
sys.modules level before importing the module under test.
"""

import asyncio
import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level mocking: stub out heavy transitive imports so we can load
# services.scheduler.engine without the full application stack.
# ---------------------------------------------------------------------------

_STUBS_INSTALLED = False
_original_modules: dict[str, ModuleType | None] = {}

# Modules that need stubbing (they either don't exist in test or have
# broken transitive imports).
_MODULES_TO_STUB = [
    "services.activity.engine",
    "services.activity.engine_execution",
    "services.activity.engine_multistep",
    "services.provenance",
    "models.agent_task",
    "models.study_goal",
    "models.user",
    "models.notification",
    "database",
    "config",
]


def _install_stubs():
    """Install lightweight module stubs so the scheduler engine can import."""
    global _STUBS_INSTALLED
    if _STUBS_INSTALLED:
        return

    for mod_name in _MODULES_TO_STUB:
        _original_modules[mod_name] = sys.modules.get(mod_name)
        if mod_name not in sys.modules:
            stub = ModuleType(mod_name)
            # Provide commonly accessed attributes
            if mod_name == "config":
                settings = MagicMock()
                settings.ambient_monitor_enabled = False
                stub.settings = settings
            elif mod_name == "database":
                stub.async_session = MagicMock()
                stub.is_sqlite = MagicMock(return_value=True)
            elif mod_name == "services.activity.engine":
                stub.submit_task = AsyncMock()
            elif mod_name == "services.provenance":
                stub.build_provenance = MagicMock(return_value={})
            elif mod_name == "models.agent_task":
                stub.AgentTask = MagicMock()
            elif mod_name == "models.study_goal":
                stub.StudyGoal = MagicMock()
            elif mod_name == "models.user":
                from sqlalchemy import Column, String
                from sqlalchemy.orm import DeclarativeBase

                class _FakeBase(DeclarativeBase):
                    pass

                class _FakeUser(_FakeBase):
                    __tablename__ = "_fake_user"
                    id = Column(String, primary_key=True)

                stub.User = _FakeUser
            elif mod_name == "models.notification":
                stub.Notification = MagicMock()
            sys.modules[mod_name] = stub

    _STUBS_INSTALLED = True


def _uninstall_stubs():
    """Restore original sys.modules entries."""
    global _STUBS_INSTALLED
    for mod_name, original in _original_modules.items():
        if original is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = original
    _STUBS_INSTALLED = False


# Install stubs and import the module under test
_install_stubs()

# Force re-import if cached with broken state
if "services.scheduler.engine" in sys.modules:
    del sys.modules["services.scheduler.engine"]

from services.scheduler.engine import (  # noqa: E402
    _SCHEDULED_JOBS,
    _broadcast_report_job,
    _for_each_user,
    _get_user_ids,
    _push_notification,
    escalation_check_job,
    start_scheduler,
    stop_scheduler,
    subscribe_sse,
    timing_analysis_job,
    unsubscribe_sse,
)


# ── Schedule configuration ──


def test_scheduled_jobs_not_empty():
    """There should be at least one scheduled job."""
    assert len(_SCHEDULED_JOBS) > 0


def test_scheduled_jobs_have_required_fields():
    """Each job tuple should have (func, trigger, job_id, name)."""
    for entry in _SCHEDULED_JOBS:
        assert len(entry) == 4
        func, trigger, job_id, name = entry
        assert callable(func)
        assert isinstance(job_id, str)
        assert isinstance(name, str)
        assert len(job_id) > 0
        assert len(name) > 0


def test_scheduled_jobs_unique_ids():
    """Job IDs should be unique."""
    ids = [entry[2] for entry in _SCHEDULED_JOBS]
    assert len(ids) == len(set(ids)), f"Duplicate job IDs found: {ids}"


def test_core_jobs_present():
    """Core jobs should be registered in the schedule."""
    job_ids = {entry[2] for entry in _SCHEDULED_JOBS}

    expected_core = {
        "agenda_tick",
        "weekly_prep",
        "scrape_refresh",
        "memory_consolidation",
        "bkt_training",
    }

    for job_id in expected_core:
        assert job_id in job_ids, f"Missing core job: {job_id}"


def test_agenda_tick_interval():
    """Agenda tick should run every 2 hours."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "agenda_tick":
            assert hasattr(trigger, "interval")
            assert trigger.interval == timedelta(hours=2)
            return
    pytest.fail("agenda_tick job not found")


def test_weekly_prep_cron_schedule():
    """Weekly prep should be a CronTrigger job."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "weekly_prep":
            # CronTrigger has start_date attribute
            assert hasattr(trigger, "start_date")
            return
    pytest.fail("weekly_prep job not found")


def test_bkt_training_scheduled():
    """BKT training job should be in the schedule."""
    job_ids = {entry[2] for entry in _SCHEDULED_JOBS}
    assert "bkt_training" in job_ids


# ── No-op stubs ──


@pytest.mark.asyncio
async def test_timing_analysis_noop():
    """Timing analysis should complete without error (no-op stub)."""
    await timing_analysis_job()


@pytest.mark.asyncio
async def test_escalation_check_noop():
    """Escalation check should complete without error (no-op stub)."""
    await escalation_check_job()


@pytest.mark.asyncio
async def test_subscribe_sse_noop():
    """subscribe_sse should be a no-op stub."""
    await subscribe_sse()


@pytest.mark.asyncio
async def test_unsubscribe_sse_noop():
    """unsubscribe_sse should be a no-op stub."""
    await unsubscribe_sse()


# ── _get_user_ids ──


@pytest.mark.asyncio
async def test_get_user_ids_returns_list():
    """_get_user_ids should return a list of UUIDs."""
    mock_session = AsyncMock()
    mock_result = MagicMock()

    user1 = uuid.uuid4()
    user2 = uuid.uuid4()
    mock_result.all.return_value = [(user1,), (user2,)]
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
        result = await _get_user_ids()

    assert result == [user1, user2]


@pytest.mark.asyncio
async def test_get_user_ids_empty():
    """_get_user_ids should return empty list when no users."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
        result = await _get_user_ids()

    assert result == []


# ── _for_each_user ──


@pytest.mark.asyncio
async def test_for_each_user_counts_successes():
    """_for_each_user should count successful processor invocations."""
    user1 = uuid.uuid4()
    user2 = uuid.uuid4()
    user3 = uuid.uuid4()

    async def processor(user_id, db):
        return user_id != user2  # user2 returns falsy

    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    with patch("services.scheduler.engine_helpers._get_user_ids", return_value=[user1, user2, user3]):
        with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
            count = await _for_each_user(processor, "test")

    assert count == 2  # user1 and user3 succeeded


@pytest.mark.asyncio
async def test_for_each_user_handles_exceptions():
    """_for_each_user should log exceptions and continue to next user."""
    user1 = uuid.uuid4()
    user2 = uuid.uuid4()

    call_count = 0

    async def processor(user_id, db):
        nonlocal call_count
        call_count += 1
        if user_id == user1:
            raise ValueError("test error")
        return True

    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    with patch("services.scheduler.engine_helpers._get_user_ids", return_value=[user1, user2]):
        with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
            count = await _for_each_user(processor, "test")

    assert count == 1  # Only user2 succeeded
    assert call_count == 2  # Both were attempted


@pytest.mark.asyncio
async def test_for_each_user_empty_users():
    """_for_each_user with no users should return 0."""
    async def processor(user_id, db):
        return True

    with patch("services.scheduler.engine_helpers._get_user_ids", return_value=[]):
        count = await _for_each_user(processor, "test")

    assert count == 0


# ── _push_notification ──


@pytest.mark.asyncio
async def test_push_notification_stores():
    """_push_notification should create and commit a Notification."""
    user_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    mock_notification_cls = MagicMock()

    with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
        with patch.dict(
            "sys.modules",
            {"models.notification": MagicMock(Notification=mock_notification_cls)},
        ):
            await _push_notification(
                user_id,
                "Test Title",
                "Test body",
                category="test_category",
            )

    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_push_notification_handles_error():
    """_push_notification should not raise on failure."""
    user_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.add.side_effect = RuntimeError("DB write failed")

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    mock_notification_cls = MagicMock()

    with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
        with patch.dict(
            "sys.modules",
            {"models.notification": MagicMock(Notification=mock_notification_cls)},
        ):
            # Should not raise despite the DB error
            await _push_notification(user_id, "Title", "Body")


@pytest.mark.asyncio
async def test_push_notification_dedup_skip():
    """_push_notification should skip inserts when dedup_key already exists."""
    user_id = uuid.uuid4()

    mock_session = AsyncMock()
    dedup_result = MagicMock()
    dedup_result.scalar_one_or_none.return_value = uuid.uuid4()
    mock_session.execute.return_value = dedup_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    mock_notification_cls = MagicMock()

    with patch("services.scheduler.engine_helpers.async_session", return_value=mock_ctx):
        with patch.dict(
            "sys.modules",
            {"models.notification": MagicMock(Notification=mock_notification_cls)},
        ):
            inserted = await _push_notification(
                user_id,
                "Daily Brief",
                "Body",
                category="daily_brief",
                dedup_key="daily_brief:2026-03-10",
            )

    assert inserted is False
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_report_job_pushes_notifications():
    """_broadcast_report_job should generate report content and push notifications."""
    import services.scheduler.engine_jobs_proactive as proactive

    user1 = uuid.uuid4()
    user2 = uuid.uuid4()

    fake_module = ModuleType("fake_report_module")
    fake_module.generate_daily = AsyncMock(side_effect=["Report A", "Report B"])

    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_ctx.__aexit__.return_value = None

    with patch.object(proactive, "_get_user_ids", return_value=[user1, user2]):
        with patch.object(proactive, "async_session", return_value=mock_ctx):
            with patch.object(proactive.importlib, "import_module", return_value=fake_module):
                with patch.object(
                    proactive,
                    "_push_notification",
                    new=AsyncMock(return_value=True),
                ) as push_mock:
                    await _broadcast_report_job(
                        name="Daily brief",
                        generator_module="fake_report_module",
                        generator_func_name="generate_daily",
                        title="Good morning",
                        category="daily_brief",
                        dedup_pattern="%Y-%m-%d",
                        action_label="View Dashboard",
                    )

    assert fake_module.generate_daily.await_count == 2
    assert push_mock.await_count == 2
    first_call_kwargs = push_mock.await_args_list[0].kwargs
    assert first_call_kwargs["title"] == "Good morning"
    assert first_call_kwargs["category"] == "daily_brief"
    assert first_call_kwargs["action_label"] == "View Dashboard"
    assert first_call_kwargs["dedup_key"].startswith("daily_brief:")


# ── start_scheduler / stop_scheduler ──


def test_start_scheduler():
    """start_scheduler should add all jobs and start the scheduler."""
    with patch("services.scheduler.engine.scheduler") as mock_scheduler:
        mock_scheduler.get_jobs.return_value = list(range(len(_SCHEDULED_JOBS)))

        start_scheduler()

        assert mock_scheduler.add_job.call_count == len(_SCHEDULED_JOBS)
        mock_scheduler.start.assert_called_once()


def test_start_scheduler_replace_existing():
    """start_scheduler should use replace_existing=True for all jobs."""
    with patch("services.scheduler.engine.scheduler") as mock_scheduler:
        mock_scheduler.get_jobs.return_value = []

        start_scheduler()

        for call in mock_scheduler.add_job.call_args_list:
            _, kwargs = call
            assert kwargs.get("replace_existing") is True


def test_stop_scheduler_running():
    """stop_scheduler should call shutdown when running."""
    with patch("services.scheduler.engine.scheduler") as mock_scheduler:
        mock_scheduler.running = True

        stop_scheduler()

        mock_scheduler.shutdown.assert_called_once_with(wait=False)


def test_stop_scheduler_not_running():
    """stop_scheduler should not call shutdown when not running."""
    with patch("services.scheduler.engine.scheduler") as mock_scheduler:
        mock_scheduler.running = False

        stop_scheduler()

        mock_scheduler.shutdown.assert_not_called()


# ── Job function signatures ──


def test_all_job_functions_are_async():
    """All scheduled job functions should be coroutine functions."""
    import inspect

    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        assert inspect.iscoroutinefunction(func), (
            f"Job '{job_id}' function {func.__name__} is not async"
        )


def test_job_names_are_descriptive():
    """Job names should be non-trivial strings."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        assert len(name) > 5, f"Job '{job_id}' has a too-short name: '{name}'"


# ── Session timing / interval checks ──


def test_scrape_refresh_hourly():
    """Scrape refresh should run every hour."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "scrape_refresh":
            assert trigger.interval == timedelta(hours=1)
            return
    pytest.fail("scrape_refresh job not found")


def test_memory_consolidation_six_hours():
    """Memory consolidation should run every 6 hours."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "memory_consolidation":
            assert trigger.interval == timedelta(hours=6)
            return
    pytest.fail("memory_consolidation job not found")


def test_smart_review_trigger_four_hours():
    """Smart review trigger should run every 4 hours."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "smart_review_trigger":
            assert trigger.interval == timedelta(hours=4)
            return
    pytest.fail("smart_review_trigger job not found")


def test_cross_course_linking_twelve_hours():
    """Cross-course linking should run every 12 hours."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "cross_course_linking":
            assert trigger.interval == timedelta(hours=12)
            return
    pytest.fail("cross_course_linking job not found")


def test_heartbeat_review_six_hours():
    """Heartbeat review should run every 6 hours."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        if job_id == "heartbeat_review":
            assert trigger.interval == timedelta(hours=6)
            return
    pytest.fail("heartbeat_review job not found")
