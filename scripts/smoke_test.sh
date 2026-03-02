#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_BASE="${API_BASE:-http://localhost:8000}"
UPLOAD_FILE="${UPLOAD_FILE:-}"
SCRAPE_URL="${SCRAPE_URL:-}"
STRICT_LLM="${STRICT_LLM:-0}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

TMP_DIR="$(create_temp_dir)"
trap 'rm -rf "$TMP_DIR"' EXIT

record_pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  log "PASS: $*"
}

record_warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  log "WARN: $*"
}

record_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  log "FAIL: $*"
}

api_call() {
  # usage: api_call METHOD PATH [BODY] [CONTENT_TYPE]
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local content_type="${4:-application/json}"
  local out_file="$TMP_DIR/resp_$(date +%s%N).json"
  local url="${API_BASE}${path}"
  local status

  if [[ -n "$body" ]]; then
    status="$(curl -sS -o "$out_file" -w "%{http_code}" -X "$method" "$url" \
      -H "Content-Type: ${content_type}" \
      --data "$body")"
  else
    status="$(curl -sS -o "$out_file" -w "%{http_code}" -X "$method" "$url")"
  fi

  API_STATUS="$status"
  API_BODY="$(cat "$out_file")"
}

run_step_required() {
  local name="$1"
  local status="$2"
  local body="$3"
  if [[ "$status" =~ ^2 ]]; then
    record_pass "$name (HTTP $status)"
  else
    record_fail "$name (HTTP $status) body=${body:0:300}"
  fi
}

run_step_optional() {
  local name="$1"
  local status="$2"
  local body="$3"
  if [[ "$status" =~ ^2 ]]; then
    record_pass "$name (HTTP $status)"
    return
  fi

  if [[ "$STRICT_LLM" == "1" ]]; then
    record_fail "$name (HTTP $status) body=${body:0:300}"
  else
    record_warn "$name (HTTP $status) body=${body:0:300}"
  fi
}

log "== OpenTutor Smoke Test =="
log "API_BASE=${API_BASE}"
log "UPLOAD_FILE=${UPLOAD_FILE:-<not set>}"
log "SCRAPE_URL=${SCRAPE_URL:-<not set>}"
log "STRICT_LLM=${STRICT_LLM}"
log ""

# 1) Health
api_call "GET" "/api/health"
run_step_required "health" "$API_STATUS" "$API_BODY"

# 2) Create course
course_name="Smoke Course $(date +%Y%m%d-%H%M%S)"
payload="{\"name\":\"${course_name}\",\"description\":\"smoke test\"}"
api_call "POST" "/api/courses/" "$payload"
run_step_required "create course" "$API_STATUS" "$API_BODY"
course_id="$(json_get_field "$API_BODY" "id")"
if [[ -z "$course_id" ]]; then
  record_fail "cannot parse created course id"
  log ""
  log "Summary: pass=${PASS_COUNT} warn=${WARN_COUNT} fail=${FAIL_COUNT}"
  exit 1
fi
record_pass "course id parsed: ${course_id}"

# 3) List courses
api_call "GET" "/api/courses/"
run_step_required "list courses" "$API_STATUS" "$API_BODY"

# 4) Content tree should be reachable
api_call "GET" "/api/courses/${course_id}/content-tree"
run_step_required "get content tree" "$API_STATUS" "$API_BODY"

# 5) Preferences set + resolve
pref_payload='{"dimension":"note_format","value":"bullet_point","scope":"global","source":"onboarding"}'
api_call "POST" "/api/preferences/" "$pref_payload"
run_step_required "set preference" "$API_STATUS" "$API_BODY"

api_call "GET" "/api/preferences/resolve?course_id=${course_id}"
run_step_required "resolve preference" "$API_STATUS" "$API_BODY"

# 6) Upload (optional when UPLOAD_FILE provided)
if [[ -n "$UPLOAD_FILE" ]]; then
  if [[ ! -f "$UPLOAD_FILE" ]]; then
    warn "UPLOAD_FILE not found: ${UPLOAD_FILE}"
  else
    out_file="$TMP_DIR/upload_resp.json"
    status="$(curl -sS -o "$out_file" -w "%{http_code}" \
      -X POST "${API_BASE}/api/content/upload" \
      -F "course_id=${course_id}" \
      -F "file=@${UPLOAD_FILE}")"
    API_BODY="$(cat "$out_file")"
    run_step_required "upload file" "$status" "$API_BODY"
  fi
else
  record_warn "skip upload: set UPLOAD_FILE=/abs/path/to/file.pdf"
fi

# 7) URL scrape (optional when SCRAPE_URL provided)
if [[ -n "$SCRAPE_URL" ]]; then
  out_file="$TMP_DIR/scrape_resp.json"
  status="$(curl -sS -o "$out_file" -w "%{http_code}" \
    -X POST "${API_BASE}/api/content/url" \
    -F "course_id=${course_id}" \
    -F "url=${SCRAPE_URL}")"
  API_BODY="$(cat "$out_file")"
  run_step_optional "scrape url" "$status" "$API_BODY"
else
  record_warn "skip scrape: set SCRAPE_URL=https://example.com/page"
fi

# 8) Quiz extraction/list (LLM-dependent)
quiz_payload="{\"course_id\":\"${course_id}\"}"
api_call "POST" "/api/quiz/extract" "$quiz_payload"
run_step_optional "quiz extract" "$API_STATUS" "$API_BODY"

api_call "GET" "/api/quiz/${course_id}"
run_step_required "quiz list" "$API_STATUS" "$API_BODY"

# 9) Chat stream (LLM-dependent, SSE endpoint)
chat_payload="{\"course_id\":\"${course_id}\",\"message\":\"Give me a short summary.\"}"
out_file="$TMP_DIR/chat_sse.txt"
status="$(curl -sS -o "$out_file" -w "%{http_code}" \
  -X POST "${API_BASE}/api/chat/" \
  -H "Content-Type: application/json" \
  --data "$chat_payload")"
body="$(head -c 400 "$out_file" || true)"
run_step_optional "chat stream" "$status" "$body"

# 10) Progress + templates + graph
api_call "GET" "/api/progress/templates"
run_step_required "list templates" "$API_STATUS" "$API_BODY"

api_call "GET" "/api/progress/courses/${course_id}"
run_step_required "course progress" "$API_STATUS" "$API_BODY"

api_call "GET" "/api/progress/courses/${course_id}/knowledge-graph"
run_step_required "knowledge graph" "$API_STATUS" "$API_BODY"

# 11) Flashcards (LLM-dependent)
fc_payload="{\"course_id\":\"${course_id}\",\"count\":5}"
api_call "POST" "/api/flashcards/generate" "$fc_payload"
run_step_optional "flashcard generate" "$API_STATUS" "$API_BODY"

# 12) Workflows (mostly LLM-dependent)
api_call "GET" "/api/workflows/weekly-prep"
run_step_optional "workflow weekly-prep" "$API_STATUS" "$API_BODY"

log ""
log "Summary: pass=${PASS_COUNT} warn=${WARN_COUNT} fail=${FAIL_COUNT}"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
