#!/usr/bin/env python3
"""Validate a verification summary JSON file for CI or local scripting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "summary_path",
        nargs="?",
        default="tmp/verification-summary.json",
        help="Path to verification-summary.json",
    )
    parser.add_argument(
        "--allow-skip",
        action="append",
        default=[],
        help="Check name allowed to appear with SKIP status. May be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary_path)
    if not summary_path.exists():
        print(f"Verification summary not found: {summary_path}", file=sys.stderr)
        return 1

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    allowed_skips = set(args.allow_skip)

    failures = [entry for entry in entries if entry.get("status") == "FAIL"]
    disallowed_skips = [
        entry for entry in entries
        if entry.get("status") == "SKIP" and entry.get("check") not in allowed_skips
    ]

    print(json.dumps({
        "summary_path": str(summary_path),
        "counts": data.get("counts", {}),
        "allowed_skips": sorted(allowed_skips),
        "failures": failures,
        "disallowed_skips": disallowed_skips,
    }, indent=2))

    if failures or disallowed_skips:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
