#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

WORKFLOW_FILE="ci.yml"
BRANCH="main"
WINDOWS=2
REPO=""

usage() {
  cat <<'USAGE'
Usage:
  scripts/check_ci_stability.sh [--repo owner/name] [--branch main] [--workflow ci.yml] [--windows 2]

Checks whether the latest N completed CI workflow runs on a branch are all successful.

Examples:
  GH_TOKEN=... bash scripts/check_ci_stability.sh --repo zijinz456/OpenTutor --windows 2
  bash scripts/check_ci_stability.sh --branch main --workflow ci.yml --windows 2
USAGE
}

resolve_repo_from_git() {
  local origin_url
  origin_url="$(git -C "${ROOT_DIR}" config --get remote.origin.url || true)"
  [[ -n "${origin_url}" ]] || return 1

  python3 - <<'PY' "${origin_url}"
import re
import sys

url = sys.argv[1].strip()
match = re.search(r"github\.com[:/]([^/]+/[^/.]+)(?:\.git)?$", url)
if not match:
    raise SystemExit(1)
print(match.group(1))
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      [[ $# -ge 2 ]] || fail "Missing value for --repo. Example: --repo owner/repo"
      REPO="$2"
      shift 2
      ;;
    --branch)
      [[ $# -ge 2 ]] || fail "Missing value for --branch. Example: --branch main"
      BRANCH="$2"
      shift 2
      ;;
    --workflow)
      [[ $# -ge 2 ]] || fail "Missing value for --workflow. Example: --workflow ci.yml"
      WORKFLOW_FILE="$2"
      shift 2
      ;;
    --windows)
      [[ $# -ge 2 ]] || fail "Missing value for --windows. Example: --windows 2"
      WINDOWS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1. Run 'bash scripts/check_ci_stability.sh --help' for usage."
      ;;
  esac
done

[[ "${WINDOWS}" =~ ^[0-9]+$ ]] || fail "--windows must be an integer. Got: ${WINDOWS}"
(( WINDOWS >= 1 )) || fail "--windows must be >= 1"

require_cmd gh python3

if [[ -z "${REPO}" ]]; then
  REPO="$(resolve_repo_from_git || true)"
fi
[[ -n "${REPO}" ]] || fail "Unable to infer GitHub repo from remote.origin.url. Pass --repo owner/repo explicitly."

if [[ -z "${GH_TOKEN:-}" && -z "${GITHUB_TOKEN:-}" ]]; then
  if ! gh auth status >/dev/null 2>&1; then
    fail "GitHub CLI is not authenticated. Run 'gh auth login' or export GH_TOKEN, then retry."
  fi
fi

TMP_JSON="$(mktemp "${TMPDIR:-/tmp}/opentutor-ci-runs.XXXXXX.json")"
trap 'rm -f "${TMP_JSON}"' EXIT

step "Fetching workflow runs"
log "  repo=${REPO} workflow=${WORKFLOW_FILE} branch=${BRANCH} windows=${WINDOWS}"
LIST_LIMIT=$(( WINDOWS * 10 ))
gh run list \
  --repo "${REPO}" \
  --workflow "${WORKFLOW_FILE}" \
  --branch "${BRANCH}" \
  --status completed \
  --limit "${LIST_LIMIT}" \
  --json status,conclusion,number,url,event > "${TMP_JSON}"

step "Evaluating stability window"
python3 - <<'PY' "${TMP_JSON}" "${WINDOWS}" "${REPO}" "${WORKFLOW_FILE}" "${BRANCH}"
import json
import sys

path, windows, repo, workflow, branch = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]

with open(path, encoding="utf-8") as fh:
    runs = json.load(fh)

if not isinstance(runs, list):
    raise SystemExit("Unexpected gh run list payload format.")
if len(runs) < windows:
    raise SystemExit(
        f"Not enough completed runs for {repo}/{workflow} on branch {branch}. "
        f"Found {len(runs)}, need {windows}."
    )

window = runs[:windows]
failed = [r for r in window if r.get("conclusion") != "success"]

print("Latest completed runs in scope:")
for run in window:
    print(
        f"- run #{run.get('number')} | conclusion={run.get('conclusion')} "
        f"| event={run.get('event')} | {run.get('url')}"
    )

if failed:
    names = ", ".join(f"#{r.get('number')}({r.get('conclusion')})" for r in failed)
    raise SystemExit(f"CI stability check failed. Non-success runs in window: {names}")

print(f"CI stability check passed: latest {windows} completed runs are all successful.")
PY
