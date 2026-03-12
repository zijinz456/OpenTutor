#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash scripts/rollback_to_tag.sh <stable-tag>" >&2
  exit 1
fi

stable_tag="$1"

if ! git rev-parse -q --verify "refs/tags/${stable_tag}" >/dev/null; then
  echo "Tag not found: ${stable_tag}" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit/stash changes before rollback." >&2
  exit 1
fi

ts="$(date +%Y%m%d-%H%M%S)"
rollback_branch="rollback/${stable_tag}-${ts}"

git switch -c "${rollback_branch}" "${stable_tag}"

cat <<EOF
Rollback branch created: ${rollback_branch}
Now validate and deploy this commit:
  git rev-parse --short HEAD
  bash scripts/dev_local.sh verify-host --ci-parity
EOF
