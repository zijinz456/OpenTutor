"""Tests for the learning report generator.

Covers:
- generate_daily_brief uses LLM with fallback
- generate_weekly_report uses LLM with fallback
- _format_fallback_report produces readable text
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.report.generator import (
    generate_daily_brief,
    generate_weekly_report,
    _format_fallback_report,
)


def _make_db():
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ── generate_daily_brief ──


@pytest.mark.asyncio
async def test_daily_brief_uses_llm():
    """Should use LLM to generate brief when available."""
    db = _make_db()

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=("Good morning! Here's your brief...", None))

    with (
        patch("services.report.generator._gather_report_data", new_callable=AsyncMock) as mock_gather,
        patch("services.llm.router.get_llm_client", return_value=mock_client),
    ):
        mock_gather.return_value = {"session_count": 2, "total_study_minutes": 45}

        result = await generate_daily_brief(uuid.uuid4(), db)

    assert "Good morning" in result
    mock_client.chat.assert_called_once()


@pytest.mark.asyncio
async def test_daily_brief_fallback_on_llm_failure():
    """Should fall back to text report when LLM fails."""
    db = _make_db()

    with (
        patch("services.report.generator._gather_report_data", new_callable=AsyncMock) as mock_gather,
        patch("services.llm.router.get_llm_client", side_effect=RuntimeError("No LLM")),
    ):
        mock_gather.return_value = {
            "session_count": 1, "total_study_minutes": 30,
            "problems_attempted": 5, "average_score": 0.8,
            "overdue_review_items": 3, "unmastered_wrong_answers": 2,
            "active_goals": [], "improved_topics": [],
        }

        result = await generate_daily_brief(uuid.uuid4(), db)

    assert "Daily Brief" in result
    assert "1 study sessions" in result


# ── generate_weekly_report ──


@pytest.mark.asyncio
async def test_weekly_report_uses_llm():
    """Should use LLM to generate weekly report."""
    db = _make_db()

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=("## This Week's Highlights...", None))

    with (
        patch("services.report.generator._gather_report_data", new_callable=AsyncMock) as mock_gather,
        patch("services.llm.router.get_llm_client", return_value=mock_client),
    ):
        mock_gather.return_value = {"session_count": 10, "total_study_minutes": 300}

        result = await generate_weekly_report(uuid.uuid4(), db)

    assert "Highlights" in result


@pytest.mark.asyncio
async def test_weekly_report_fallback_on_llm_failure():
    """Should fall back to text report when LLM fails."""
    db = _make_db()

    with (
        patch("services.report.generator._gather_report_data", new_callable=AsyncMock) as mock_gather,
        patch("services.llm.router.get_llm_client", side_effect=RuntimeError("No LLM")),
    ):
        mock_gather.return_value = {
            "session_count": 5, "total_study_minutes": 120,
            "problems_attempted": 20, "average_score": 0.85,
            "overdue_review_items": 7, "unmastered_wrong_answers": 3,
            "active_goals": [{"title": "Master calculus", "days_until_target": 14}],
            "improved_topics": [],
        }

        result = await generate_weekly_report(uuid.uuid4(), db)

    assert "Weekly Summary" in result
    assert "5 study sessions" in result


# ── _format_fallback_report ──


def test_fallback_report_daily():
    """Fallback daily report should include key metrics."""
    data = {
        "session_count": 2,
        "total_study_minutes": 45,
        "problems_attempted": 10,
        "average_score": 0.75,
        "overdue_review_items": 3,
        "unmastered_wrong_answers": 5,
        "active_goals": [{"title": "Learn math", "days_until_target": 5}],
        "improved_topics": [],
    }

    result = _format_fallback_report(data, "daily")

    assert "Daily Brief" in result
    assert "2 study sessions" in result
    assert "45 minutes" in result
    assert "10 problems" in result
    assert "3 items overdue" in result
    assert "Learn math" in result
    assert "(due in 5d)" in result


def test_fallback_report_weekly():
    """Fallback weekly report should use 'Weekly Summary' header."""
    data = {
        "session_count": 0,
        "total_study_minutes": 0,
        "problems_attempted": 0,
        "average_score": 0,
        "overdue_review_items": 0,
        "unmastered_wrong_answers": 0,
        "active_goals": [],
        "improved_topics": [],
    }

    result = _format_fallback_report(data, "weekly")

    assert "Weekly Summary" in result
    assert "No study sessions" in result


def test_fallback_report_no_deadline():
    """Goals without a deadline should not show (due in Xd)."""
    data = {
        "session_count": 1,
        "total_study_minutes": 20,
        "problems_attempted": 0,
        "average_score": 0,
        "overdue_review_items": 0,
        "unmastered_wrong_answers": 0,
        "active_goals": [{"title": "Explore physics", "days_until_target": None}],
        "improved_topics": [],
    }

    result = _format_fallback_report(data, "daily")

    assert "Explore physics" in result
    assert "(due in" not in result
