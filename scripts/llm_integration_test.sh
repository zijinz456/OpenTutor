#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8004}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"

OPENAI_KEY="${OPENAI_API_KEY:-}"
ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"
DEEPSEEK_KEY="${DEEPSEEK_API_KEY:-}"

if [[ -z "${OPENAI_KEY}" && -z "${ANTHROPIC_KEY}" && -z "${DEEPSEEK_KEY}" ]]; then
  echo "FAIL: No real LLM key in environment."
  echo "Set one of OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY and rerun."
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "== Real LLM Integration Test =="
echo "API_BASE=${API_BASE}"

# Health check
status="$(curl -sS -o "$TMP_DIR/health.json" -w "%{http_code}" "${API_BASE}/api/health")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: health check failed (HTTP $status)"
  cat "$TMP_DIR/health.json" || true
  exit 1
fi
echo "PASS: health"

# Create a fresh course
course_name="LLM Integration $(date +%Y%m%d-%H%M%S)"
payload="{\"name\":\"${course_name}\",\"description\":\"real llm integration\"}"
status="$(curl -sS -o "$TMP_DIR/course.json" -w "%{http_code}" \
  -X POST "${API_BASE}/api/courses/" \
  -H "Content-Type: application/json" \
  --data "$payload")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: create course failed (HTTP $status)"
  cat "$TMP_DIR/course.json" || true
  exit 1
fi

course_id="$(python3 - <<'PY' "$TMP_DIR/course.json"
import json, sys
with open(sys.argv[1]) as f:
    print(json.load(f)["id"])
PY
)"
echo "PASS: created course ${course_id}"

# Real chat stream call (SSE)
chat_payload="{\"course_id\":\"${course_id}\",\"message\":\"Give me a concise summary of this course in 2 bullet points.\"}"
status="$(curl -sS -o "$TMP_DIR/chat.txt" -w "%{http_code}" \
  -X POST "${API_BASE}/api/chat/" \
  -H "Content-Type: application/json" \
  --data "$chat_payload" \
  --max-time "${TIMEOUT_SECONDS}")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: chat stream failed (HTTP $status)"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

if rg -q "No LLM API key configured|local fallback response" "$TMP_DIR/chat.txt"; then
  echo "FAIL: chat used mock fallback instead of real provider"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi

if ! rg -q "event: message|event: done" "$TMP_DIR/chat.txt"; then
  echo "FAIL: chat stream did not contain expected SSE events"
  head -c 500 "$TMP_DIR/chat.txt" || true
  exit 1
fi
echo "PASS: real chat stream"

# Real workflow call
status="$(curl -sS -o "$TMP_DIR/weekly.json" -w "%{http_code}" \
  "${API_BASE}/api/workflows/weekly-prep" \
  --max-time "${TIMEOUT_SECONDS}")"
if [[ ! "$status" =~ ^2 ]]; then
  echo "FAIL: weekly-prep failed (HTTP $status)"
  cat "$TMP_DIR/weekly.json" || true
  exit 1
fi

if rg -q "No LLM API key configured|local fallback response" "$TMP_DIR/weekly.json"; then
  echo "FAIL: weekly-prep used mock fallback instead of real provider"
  cat "$TMP_DIR/weekly.json" || true
  exit 1
fi
echo "PASS: real weekly-prep workflow"

echo "PASS: Real LLM integration checks completed"
