#!/usr/bin/env python3
"""Performance benchmark suite for OpenTutor API.

Measures response times for key endpoints and reports p50/p95/p99 latencies.
Requires a running API server.

Usage:
    python scripts/benchmark.py [--base-url http://localhost:8000/api] [--iterations 20]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
import urllib.error


def _request(url: str, method: str = "GET", data: dict | None = None, timeout: int = 30) -> tuple[int, float]:
    """Make an HTTP request and return (status_code, elapsed_seconds)."""
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            elapsed = time.perf_counter() - start
            return resp.status, elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - start
        return e.code, elapsed
    except Exception:
        elapsed = time.perf_counter() - start
        return 0, elapsed


def _percentile(data: list[float], pct: float) -> float:
    """Calculate percentile from sorted data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * pct / 100
    lower = int(idx)
    upper = min(lower + 1, len(sorted_data) - 1)
    weight = idx - lower
    return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight


def run_benchmark(base_url: str, iterations: int) -> dict:
    """Run benchmark suite and return results."""
    endpoints = [
        ("Health (live)", "GET", "/health/live", None),
        ("Health (ready)", "GET", "/health/ready", None),
        ("Health (full)", "GET", "/health", None),
        ("List courses", "GET", "/courses/", None),
    ]

    results = {}
    failed = False

    for name, method, path, data in endpoints:
        url = f"{base_url}{path}"
        latencies: list[float] = []
        errors = 0

        for _ in range(iterations):
            status, elapsed = _request(url, method, data)
            if 200 <= status < 300:
                latencies.append(elapsed * 1000)  # ms
            else:
                errors += 1

        if latencies:
            result = {
                "p50_ms": round(_percentile(latencies, 50), 1),
                "p95_ms": round(_percentile(latencies, 95), 1),
                "p99_ms": round(_percentile(latencies, 99), 1),
                "mean_ms": round(statistics.mean(latencies), 1),
                "min_ms": round(min(latencies), 1),
                "max_ms": round(max(latencies), 1),
                "errors": errors,
                "samples": len(latencies),
            }
        else:
            result = {"errors": errors, "samples": 0, "status": "all_failed"}
            failed = True

        results[name] = result

    return {"endpoints": results, "iterations": iterations, "base_url": base_url, "all_passed": not failed}


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenTutor API performance benchmark")
    parser.add_argument("--base-url", default="http://localhost:8000/api", help="API base URL")
    parser.add_argument("--iterations", type=int, default=20, help="Requests per endpoint")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--threshold-ms", type=float, default=500, help="p95 threshold in ms (exit 1 if exceeded)")
    args = parser.parse_args()

    print(f"Benchmarking {args.base_url} ({args.iterations} iterations per endpoint)...\n")

    results = run_benchmark(args.base_url, args.iterations)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"{'Endpoint':<25} {'p50':>8} {'p95':>8} {'p99':>8} {'mean':>8} {'errors':>7}")
        print("-" * 73)
        for name, data in results["endpoints"].items():
            if data.get("status") == "all_failed":
                print(f"{name:<25} {'FAILED':>8}")
            else:
                print(
                    f"{name:<25} {data['p50_ms']:>7.1f}ms {data['p95_ms']:>7.1f}ms "
                    f"{data['p99_ms']:>7.1f}ms {data['mean_ms']:>7.1f}ms {data['errors']:>7}"
                )

    # Check threshold
    regression = False
    for name, data in results["endpoints"].items():
        p95 = data.get("p95_ms", 0)
        if p95 > args.threshold_ms:
            print(f"\nREGRESSION: {name} p95 ({p95:.1f}ms) exceeds threshold ({args.threshold_ms}ms)")
            regression = True

    if regression or not results["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
