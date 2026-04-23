#!/usr/bin/env python
"""CLI entry point for the LLM evaluation harness.

Loads one or more fixture suites, runs them through
``services.eval.runner.run_eval_suite``, prints a Markdown report, and
exits non-zero if the overall score falls below ``--threshold``. Useful
for manual drift checks and for CI "quality gate" jobs.

Usage::

    python scripts/run_eval.py
    python scripts/run_eval.py --suite quiz_30q --threshold 0.8
    python scripts/run_eval.py --output-json
    python scripts/run_eval.py --model gpt-4o-mini

Fixture paths resolve relative to ``apps/api/tests/eval/fixtures`` and
the ``.yaml`` extension is added if missing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure ``apps/api`` is importable when invoked as a plain script
# (``python scripts/run_eval.py``). When imported as a module via
# ``python -m scripts.run_eval`` this is already handled.
_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from schemas.eval import EvalReport  # noqa: E402
from services.eval.runner import run_eval_suite  # noqa: E402

DEFAULT_SUITES = ["quiz_30q", "humaneval_subset", "gsm8k_subset"]
FIXTURE_DIR = _API_DIR / "tests" / "eval" / "fixtures"
REPORTS_DIR = _API_DIR / "tests" / "eval" / "reports"


def _resolve_suite_paths(suite_names: list[str]) -> list[Path]:
    """Turn suite names/stems into absolute YAML fixture paths."""
    paths: list[Path] = []
    for name in suite_names:
        stem = name.strip()
        if not stem:
            continue
        candidate = FIXTURE_DIR / (stem if stem.endswith(".yaml") else f"{stem}.yaml")
        paths.append(candidate)
    return paths


def _format_markdown(report: EvalReport) -> str:
    """Render an EvalReport to a human-readable Markdown string."""
    lines: list[str] = []
    lines.append("# Eval Report")
    lines.append("")
    lines.append(f"**Model:** {report.model}")
    lines.append(f"**Provider:** {report.provider}")
    lines.append(f"**Date:** {report.started_at}")
    lines.append(f"**Duration:** {report.duration_s}s")
    lines.append(
        f"**Overall:** {report.passed} / {report.total} passed "
        f"({report.score_pct:.1f}%)"
    )
    lines.append("")

    if report.category_scores:
        lines.append("## Category scores")
        lines.append("")
        lines.append("| Category | Passed | Total | Score |")
        lines.append("|---|---|---|---|")
        by_cat: dict[str, tuple[int, int]] = {}
        for r in report.results:
            p, t = by_cat.get(r.category, (0, 0))
            by_cat[r.category] = (p + (1 if r.passed else 0), t + 1)
        for cat, (p, t) in sorted(by_cat.items()):
            pct = report.category_scores.get(cat, 0.0)
            lines.append(f"| {cat} | {p} | {t} | {pct:.1f}% |")
        lines.append("")

    failures = [r for r in report.results if not r.passed]
    if failures:
        lines.append(f"## Failures ({len(failures)})")
        lines.append("")
        for r in failures:
            snippet = (r.actual or "").strip().replace("\n", " ")
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            err = f" [ERROR: {r.error}]" if r.error else ""
            lines.append(
                f"- **{r.question_id}** (`{r.grade_mode}`): expected "
                f"`{r.expected}`, got: {snippet!r}{err}"
            )
        lines.append("")

    return "\n".join(lines)


def _write_json_report(report: EvalReport) -> Path:
    """Persist the full report as JSON under ``tests/eval/reports/``."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = report.model.replace("/", "_").replace(":", "_")
    path = REPORTS_DIR / f"{ts}-{safe_model}.json"
    path.write_text(
        json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the LLM evaluation harness.")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Minimum overall score (0-1) required to exit 0. Default: 0.70",
    )
    p.add_argument(
        "--suite",
        type=str,
        default=",".join(DEFAULT_SUITES),
        help=(
            "Comma-separated suite names (stems under tests/eval/fixtures). "
            f"Default: {','.join(DEFAULT_SUITES)}"
        ),
    )
    p.add_argument(
        "--output-json",
        action="store_true",
        help="Also write a machine-readable JSON report to tests/eval/reports/.",
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override LLM_MODEL env var for this run (hint to the router).",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent LLM calls. Default: 5",
    )
    return p.parse_args(argv)


async def _amain(args: argparse.Namespace) -> int:
    # Allow ``--model`` to influence which concrete model the router picks
    # via the existing LLM_MODEL knob. Set BEFORE importing the router —
    # but runner imports it lazily, so setting here is sufficient.
    if args.model:
        os.environ["LLM_MODEL"] = args.model

    suite_names = [s for s in args.suite.split(",") if s.strip()]
    fixture_paths = _resolve_suite_paths(suite_names)

    report = await run_eval_suite(
        fixture_paths,
        model_hint=args.model,
        max_concurrency=args.concurrency,
    )

    print(_format_markdown(report))

    if args.output_json:
        path = _write_json_report(report)
        print(f"\n[eval] JSON report written to: {path}")

    threshold_pct = args.threshold * 100.0
    if report.score_pct < threshold_pct:
        print(
            f"\n[eval] FAILED: score {report.score_pct:.1f}% < threshold "
            f"{threshold_pct:.1f}%",
            file=sys.stderr,
        )
        return 1
    print(
        f"\n[eval] PASSED: score {report.score_pct:.1f}% >= threshold "
        f"{threshold_pct:.1f}%"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
