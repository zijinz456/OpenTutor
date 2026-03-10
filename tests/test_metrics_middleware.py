"""Tests for middleware/metrics.py — in-process metrics collection."""

import uuid

import pytest

from middleware.metrics import (
    _Histogram,
    _MetricsStore,
    _normalize_path,
    get_metrics,
    record_llm_call,
    _store,
)


# ── _Histogram tests ──

def test_histogram_empty_percentile():
    """Empty histogram returns 0.0 for any percentile."""
    h = _Histogram()
    assert h.percentile(50) == 0.0
    assert h.percentile(99) == 0.0
    assert h.count() == 0


def test_histogram_record_and_percentile():
    """Histogram records values and computes correct percentiles."""
    h = _Histogram()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
        h.record(v)
    assert h.count() == 5
    assert h.percentile(50) == 30.0
    # p0 should give the first element
    assert h.percentile(0) == 10.0


def test_histogram_sorted_order():
    """Values are kept in sorted order regardless of insertion order."""
    h = _Histogram()
    h.record(50.0)
    h.record(10.0)
    h.record(30.0)
    assert h.values == [10.0, 30.0, 50.0]


def test_histogram_downsamples_at_max():
    """Histogram downsamples when max_samples is reached."""
    h = _Histogram(max_samples=10)
    for i in range(10):
        h.record(float(i))
    assert h.count() == 10
    # Recording one more triggers downsample
    h.record(100.0)
    assert h.count() < 12  # Should have downsampled


# ── _normalize_path tests ──

def test_normalize_path_replaces_uuid():
    """UUIDs in paths are replaced with {id}."""
    path = f"/api/courses/{uuid.uuid4()}/notes"
    result = _normalize_path(path)
    assert "{id}" in result
    assert result.endswith("/notes")


def test_normalize_path_replaces_numeric_id():
    """Numeric path segments are replaced with {id}."""
    assert _normalize_path("/api/items/12345") == "/api/items/{id}"


def test_normalize_path_no_ids():
    """Paths without IDs are unchanged."""
    assert _normalize_path("/api/health") == "/api/health"


# ── record_llm_call tests ──

def test_record_llm_call_increments():
    """record_llm_call updates global LLM counters."""
    initial_count = _store.llm_call_count
    initial_tokens = _store.llm_total_tokens

    record_llm_call(duration_ms=150.0, prompt_tokens=100, completion_tokens=50)

    assert _store.llm_call_count == initial_count + 1
    assert _store.llm_total_tokens == initial_tokens + 150
    assert _store.llm_latency.count() > 0


# ── get_metrics tests ──

def test_get_metrics_structure():
    """get_metrics returns dict with expected top-level keys."""
    m = get_metrics()
    assert "uptime_seconds" in m
    assert "total_requests" in m
    assert "total_errors" in m
    assert "error_rate" in m
    assert "latency" in m
    assert "llm" in m
    assert "endpoints" in m


def test_get_metrics_latency_keys():
    """Latency section has p50, p90, p95, p99."""
    m = get_metrics()
    for key in ["p50_ms", "p90_ms", "p95_ms", "p99_ms"]:
        assert key in m["latency"]


def test_get_metrics_llm_keys():
    """LLM section has expected keys."""
    m = get_metrics()
    for key in ["calls", "total_tokens", "prompt_tokens", "completion_tokens", "p50_ms", "p95_ms"]:
        assert key in m["llm"]
