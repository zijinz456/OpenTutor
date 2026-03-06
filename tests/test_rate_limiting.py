"""Tests for GCRA cost-aware rate limiting."""

import time
from unittest.mock import patch

import pytest


# ── Cost Matrix Tests ──


def test_cost_matrix_health_is_zero():
    from middleware.cost_matrix import get_endpoint_cost

    assert get_endpoint_cost("/api/health") == 0
    assert get_endpoint_cost("/docs") == 0
    assert get_endpoint_cost("/openapi.json") == 0


def test_cost_matrix_chat_stream_is_high():
    from middleware.cost_matrix import get_endpoint_cost

    cost = get_endpoint_cost("/api/chat/")
    assert cost == 30


def test_cost_matrix_quiz_extract():
    from middleware.cost_matrix import get_endpoint_cost

    assert get_endpoint_cost("/api/quiz/extract") == 50


def test_cost_matrix_quiz_extract_is_very_high():
    from middleware.cost_matrix import get_endpoint_cost

    # Quiz extraction is one of the highest-cost endpoints
    assert get_endpoint_cost("/api/quiz/extract") >= 50


def test_cost_matrix_write_method_multiplier():
    from middleware.cost_matrix import get_endpoint_cost

    get_cost = get_endpoint_cost("/api/courses", "GET")
    post_cost = get_endpoint_cost("/api/courses", "POST")
    assert post_cost > get_cost
    assert post_cost == 3  # 2 * 1.5 = 3.0 → 3


def test_cost_matrix_prefix_matching():
    from middleware.cost_matrix import get_endpoint_cost

    assert get_endpoint_cost("/api/courses/abc-123/chat") == 30
    assert get_endpoint_cost("/api/courses/abc-123") == 3
    assert get_endpoint_cost("/api/progress/overview") == 3


def test_cost_matrix_default_for_unknown():
    from middleware.cost_matrix import get_endpoint_cost, DEFAULT_COST

    assert get_endpoint_cost("/api/unknown-endpoint") == DEFAULT_COST


# ── Rate Bucket Tests ──


def test_cost_bucket_allows_under_budget():
    from middleware.security import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None, cost_aware=True, cost_budget_per_minute=500)
    # First request with cost 30 should pass
    allowed, _ = limiter._check_cost_rate("test-ip", 30)
    assert allowed is True


def test_cost_bucket_denies_over_budget():
    from middleware.security import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None, cost_aware=True, cost_budget_per_minute=100)
    # Drain the bucket with 4 requests of cost 30 each (total 120 > 100)
    limiter._check_cost_rate("test-ip", 30)
    limiter._check_cost_rate("test-ip", 30)
    limiter._check_cost_rate("test-ip", 30)
    allowed, retry_after = limiter._check_cost_rate("test-ip", 30)
    assert allowed is False
    assert retry_after > 0


def test_cost_bucket_refills_over_time():
    from middleware.security import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None, cost_aware=True, cost_budget_per_minute=60)
    # Use all budget
    limiter._check_cost_rate("test-ip", 60)
    allowed, _ = limiter._check_cost_rate("test-ip", 1)
    assert allowed is False

    # Simulate time passing (manipulate bucket directly)
    bucket = limiter._buckets["test-ip"]
    bucket.last_refill -= 10  # 10 seconds ago → refill 10 tokens
    allowed, _ = limiter._check_cost_rate("test-ip", 5)
    assert allowed is True


def test_retry_after_header_calculated():
    from middleware.security import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None, cost_aware=True, cost_budget_per_minute=60)
    # Drain budget
    limiter._check_cost_rate("test-ip", 60)
    allowed, retry_after = limiter._check_cost_rate("test-ip", 10)
    assert allowed is False
    # Need 10 tokens, refill rate = 1/sec, so ~10 seconds
    assert 9.0 <= retry_after <= 11.0


def test_simple_mode_backward_compat():
    from middleware.security import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None, cost_aware=False, default_rpm=60, llm_rpm=10)
    # Should work the same as before
    allowed = limiter._check_simple_rate("test-ip:general", 60)
    assert allowed is True


def test_zero_cost_endpoint_always_passes():
    from middleware.cost_matrix import get_endpoint_cost

    assert get_endpoint_cost("/api/health") == 0
    assert get_endpoint_cost("/docs") == 0
