#!/usr/bin/env bash

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() {
  printf '%s\n' "$*"
}

step() {
  printf '\n== %s ==\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: ${cmd}"
  done
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    printf '%s\n' "${ROOT_DIR}/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
}

require_python_311() {
  local py_bin="$1"
  local version

  version="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "${version}" != "3.11" ]]; then
    fail "OpenTutor requires Python 3.11 for local verification. Found ${version} at ${py_bin}."
  fi
}

wait_for_url() {
  local label="$1"
  local url="$2"
  local timeout_seconds="${3:-180}"
  local started_at
  local status

  started_at="$(date +%s)"
  while true; do
    status="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || true)"
    if [[ "$status" =~ ^(2|3) ]]; then
      log "READY: ${label} (${url})"
      return 0
    fi
    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      fail "${label} did not become ready within ${timeout_seconds}s: ${url}"
    fi
    sleep 2
  done
}

has_real_llm_env() {
  local keys=(
    OPENAI_API_KEY
    ANTHROPIC_API_KEY
    DEEPSEEK_API_KEY
    OPENROUTER_API_KEY
    GEMINI_API_KEY
    GROQ_API_KEY
  )
  local key
  for key in "${keys[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      return 0
    fi
  done
  return 1
}

compose() {
  docker compose "$@"
}
