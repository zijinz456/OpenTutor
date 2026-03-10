#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

ROUND_LABEL="round-1"
REPORT_ROOT="${REPORT_ROOT:-${ROOT_DIR}/tmp/release-rehearsal}"
REHEARSAL_API_PORT="${REHEARSAL_API_PORT:-38000}"
REHEARSAL_WEB_PORT="${REHEARSAL_WEB_PORT:-33000}"
API_BASE_URL=""
WEB_BASE_URL=""
COMPOSE_PROJECT=""

REPORT_DIR=""
REPORT_FILE=""
LOG_DIR=""
FAIL_COUNT=0
PASS_COUNT=0
SKIP_COUNT=0
ORIGINAL_ENV_PRESENT=0
ENV_BACKUP_FILE=""
STACK_ATTEMPTED=0

usage() {
  cat <<'USAGE'
Usage:
  scripts/release_rehearsal_round.sh [--round LABEL] [--report-root PATH]

Runs one clean-environment release rehearsal round on the current host:
  1) quickstart first-run check (host mode)
  2) docker first-run check (up --build + health)
  3) CI parity check
  4) strict benchmark gate

Examples:
  bash scripts/release_rehearsal_round.sh --round round-1
  bash scripts/release_rehearsal_round.sh --round round-2 --report-root tmp/release-rehearsal

Environment overrides:
  REHEARSAL_API_PORT=38000
  REHEARSAL_WEB_PORT=33000
  REHEARSAL_COMPOSE_PROJECT=opentutor_release_round_1
USAGE
}

record_result() {
  local status="$1"
  local check="$2"
  local details="$3"
  printf '| %s | %s | %s |\n' "${status}" "${check}" "${details}" >> "${REPORT_FILE}"
}

record_skip() {
  local check="$1"
  local reason="$2"
  SKIP_COUNT=$((SKIP_COUNT + 1))
  log "SKIP: ${check} (${reason})"
  record_result "SKIP" "${check}" "${reason}"
}

run_check() {
  local check="$1"
  shift

  local slug
  local log_file
  local rc
  slug="$(printf '%s' "${check}" | LC_ALL=C tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
  log_file="${LOG_DIR}/${slug}.log"

  step "${check}"

  set +e
  {
    printf '$'
    for arg in "$@"; do
      printf ' %q' "${arg}"
    done
    printf '\n'
    "$@"
  } >"${log_file}" 2>&1
  rc=$?
  set -e

  if (( rc == 0 )); then
    PASS_COUNT=$((PASS_COUNT + 1))
    log "  PASS"
    record_result "PASS" "${check}" "ok"
    return 0
  fi

  FAIL_COUNT=$((FAIL_COUNT + 1))
  log "  FAIL (exit ${rc})"
  log "  See log: ${log_file}"
  record_result "FAIL" "${check}" "exit ${rc} (see ${log_file})"
  return 1
}

cleanup() {
  if (( STACK_ATTEMPTED )) && command -v docker >/dev/null 2>&1; then
    env \
      COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}" \
      API_PORT="${REHEARSAL_API_PORT}" \
      WEB_PORT="${REHEARSAL_WEB_PORT}" \
      bash "${ROOT_DIR}/scripts/dev_local.sh" down >/dev/null 2>&1 || true
  fi

  if (( ORIGINAL_ENV_PRESENT )); then
    if [[ -n "${ENV_BACKUP_FILE}" && -f "${ENV_BACKUP_FILE}" ]]; then
      mv "${ENV_BACKUP_FILE}" "${ROOT_DIR}/.env"
    fi
  else
    rm -f "${ROOT_DIR}/.env"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --round)
      [[ $# -ge 2 ]] || fail "Missing value for --round. Example: --round round-1"
      ROUND_LABEL="$2"
      shift 2
      ;;
    --report-root)
      [[ $# -ge 2 ]] || fail "Missing value for --report-root. Example: --report-root tmp/release-rehearsal"
      REPORT_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1. Run 'bash scripts/release_rehearsal_round.sh --help' for usage."
      ;;
  esac
done

require_cmd bash curl
[[ -f "${ROOT_DIR}/.env.example" ]] || fail "Missing .env.example. Restore it before running release rehearsal."

ROUND_SLUG="$(printf '%s' "${ROUND_LABEL}" | LC_ALL=C tr -cs 'a-zA-Z0-9' '_')"
COMPOSE_PROJECT="${REHEARSAL_COMPOSE_PROJECT:-opentutor_release_${ROUND_SLUG}}"
API_BASE_URL="http://localhost:${REHEARSAL_API_PORT}/api"
WEB_BASE_URL="http://localhost:${REHEARSAL_WEB_PORT}"

REPORT_DIR="${REPORT_ROOT}/${ROUND_LABEL}"
REPORT_FILE="${REPORT_DIR}/summary.md"
LOG_DIR="${REPORT_DIR}/logs"
mkdir -p "${LOG_DIR}"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  ORIGINAL_ENV_PRESENT=1
  ENV_BACKUP_FILE="${REPORT_DIR}/env.backup"
  cp "${ROOT_DIR}/.env" "${ENV_BACKUP_FILE}"
fi

trap cleanup EXIT

cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
set_env_value "${ROOT_DIR}/.env" "API_PORT" "${REHEARSAL_API_PORT}"
set_env_value "${ROOT_DIR}/.env" "WEB_PORT" "${REHEARSAL_WEB_PORT}"

cat > "${REPORT_FILE}" <<REPORT
# Release Rehearsal ${ROUND_LABEL}

- Generated at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
- Host: $(hostname)
- Compose project: ${COMPOSE_PROJECT}
- API base: ${API_BASE_URL}
- Web base: ${WEB_BASE_URL}

| Status | Check | Details |
|---|---|---|
REPORT

if ! run_check "Local mode precheck" bash "${ROOT_DIR}/scripts/check_local_mode.sh" --env-file "${ROOT_DIR}/.env" --skip-api; then
  :
fi
if ! run_check "Quickstart first-run (exit-after-ready)" env API_PORT="${REHEARSAL_API_PORT}" WEB_PORT="${REHEARSAL_WEB_PORT}" bash "${ROOT_DIR}/scripts/quickstart.sh" --exit-after-ready; then
  :
fi

DOCKER_UP_OK=0
STACK_ATTEMPTED=1
if run_check "Docker first-run (up --build)" env COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}" API_PORT="${REHEARSAL_API_PORT}" WEB_PORT="${REHEARSAL_WEB_PORT}" bash "${ROOT_DIR}/scripts/dev_local.sh" up --build; then
  DOCKER_UP_OK=1
fi

if (( DOCKER_UP_OK )); then
  if ! run_check "Docker API health" curl -fsS "${API_BASE_URL}/health"; then
    :
  fi
  if ! run_check "Docker Web health" curl -fsS "${WEB_BASE_URL}"; then
    :
  fi
  if ! run_check "CI parity host verification" env COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}" API_PORT="${REHEARSAL_API_PORT}" WEB_PORT="${REHEARSAL_WEB_PORT}" bash "${ROOT_DIR}/scripts/dev_local.sh" verify-host --ci-parity; then
    :
  fi
  if ! run_check "Strict benchmark gate (running stack)" bash -lc "API_BASE='${API_BASE_URL}' STRICT_BENCHMARK=1 bash '${ROOT_DIR}/scripts/run_regression_benchmark.sh'"; then
    :
  fi
else
  record_skip "Docker API health" "Skipped because docker stack failed to start"
  record_skip "Docker Web health" "Skipped because docker stack failed to start"
  record_skip "CI parity host verification" "Skipped because docker stack failed to start"
  record_skip "Strict benchmark gate (running stack)" "Skipped because docker stack failed to start"
fi

if ! run_check "Docker teardown" env COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT}" API_PORT="${REHEARSAL_API_PORT}" WEB_PORT="${REHEARSAL_WEB_PORT}" bash "${ROOT_DIR}/scripts/dev_local.sh" down; then
  :
fi

log ""
log "Release rehearsal report: ${REPORT_FILE}"
log "Passed: ${PASS_COUNT}, Failed: ${FAIL_COUNT}, Skipped: ${SKIP_COUNT}"

if (( FAIL_COUNT > 0 )); then
  exit 1
fi
