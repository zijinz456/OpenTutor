# Phase 16c — drills E2E manual smoke (GATE-1)

**Purpose.** Walk the drill flow end-to-end as a real learner would.
10 steps, ~3 minutes, no guessing. Run this before closing GATE-1.

**Prereqs.** Docker stack up (`docker compose up -d`), a test user
account available, browser open to a fresh tab. The three commits this
script is written against are:

- `content(drills): CS50P lectures 0-2 (...)` — 30 CS50P drills seeded.
- `feat(drills): integration test + pill progress + GATE-1 smoke script` —
  pill shows `пройдено X / Y`, E2E pytest passes.
- Earlier Phase 16c work on py4e (161 drills, 16 modules).

---

## 1. `alembic upgrade head`

Run `docker exec opentutor-api alembic upgrade head`.

**Expected.** Exit code 0, final line ends with the latest revision id
(e.g. `20260425_0003_...` or later). Schema drift is a GATE-1 blocker.

**If fails.** Check the alembic migration file for a syntax error or a
column collision against an unreverted prior migration. Re-run with
`--sql` to dump the pending DDL before applying.

## 2. `PYTHONIOENCODING=utf-8 python scripts/seed_drill_courses.py`

Run inside the api container: `docker exec -e PYTHONIOENCODING=utf-8
opentutor-api python scripts/seed_drill_courses.py`.

**Expected.** Summary line prints `courses=2 modules=19 drills=191
dropped=0` (or close — py4e=16 modules / 161 drills plus cs50p=3
modules / 30 drills). `dropped=0` is the strict-mode contract.

**If fails.** Re-run with `--dry-run` to isolate the failing drill.
Most likely culprit: a reference solution that doesn't pass its own
hidden_tests. The error names the offending module + drill slug — fix
in the source YAML, not the DB.

## 3. Start dev server (if not running)

`docker compose up -d web api redis`.

**Expected.** `docker ps` shows `opentutor-web`, `opentutor-api`,
`opentutor-redis` all `Up` within ~15s. `curl
http://localhost:8000/api/healthz` returns 200.

**If fails.** `docker compose logs api --tail=50` will show the
startup exception. Common cause: missing env var — confirm `.env`
exists and contains `DATABASE_URL` plus any secrets the new migration
expects.

## 4. Open `http://localhost:3000/` — dashboard pill visible

Log in with the test user, land on the dashboard.

**Expected.** `<DrillCoursesPill>` renders inside the dashboard
(data-testid `drill-courses-pill`). The subtitle line reads
`19 модулів у 2 курсах`. For a new user, the second line reads
`пройдено: 0 / 191 — почни з будь-якого` (ADHD-safe kick-off copy).

**If fails.** Open devtools → Network tab, re-filter on `/api/drills/courses`.
If the call returns 401, the user session didn't propagate — log out
and back in. If it returns `[]`, step 2 didn't actually seed the DB —
re-run it with verbose output.

## 5. Click "Практика" → `/courses` — 2 courses visible

**Expected.** The pill's CTA routes to `/courses`. The list page
renders two cards: `PY4E` (16 modules, 161 drills) and `CS50P` (3
modules, 30 drills). No empty-state copy visible.

**If fails.** Re-check `/api/drills/courses` payload in devtools. If
one course is missing, re-seed. If both are there but the page shows
empty, check the `listDrillCourses` response shape matches the
`DrillCourseOut` TS type — stale frontend build is a common cause
(restart `opentutor-web`).

## 6. Click py4e → `/courses/py4e` — 16 modules

**Expected.** The TOC page shows all 16 py4e modules (`ch01`…`ch16`)
in order, each with its drill count chip. Drill titles preview under
each module header.

**If fails.** A TOC request that returns 404 with `course_not_found`
means the slug on the URL doesn't match the DB row — re-check the
`listDrillCourses` response's `slug` field and that the link component
is using it verbatim, not a lowercased/transformed variant.

## 7. Click drill 1 from ch01 → `/practice/{id}` — starter + hint UI

**Expected.** The practice page opens with the drill title, the
`why_it_matters` line, the `starter_code` pre-filled in the textarea,
and the first hint collapsed (click to reveal). `hidden_tests` is NOT
visible anywhere — if it is, that's a security bug.

**If fails.** If starter_code is empty, the drill row is corrupt —
reseed. If hidden_tests appears, revert to the server-schema contract
and check `routers/drills.py::_drill_to_out` is not projecting
`hidden_tests` into the response.

## 8. Submit wrong code → amber feedback, not red; skip button available

Paste something that obviously fails (e.g. `print("")`) and submit.

**Expected.** Feedback banner uses amber / neutral colour (never red),
text reads `"Ще не все — подивись на останній assert і спробуй ще."` —
no "wrong"/"failed"/"incorrect" vocabulary, no ❌ glyph. A "Пропустити"
(skip) button is present so the learner isn't trapped. Runner output
visible below for debugging.

**If fails.** If the banner is red or the copy includes a punitive
word, regression in `services/drill_submission._FEEDBACK_FAIL` — that
string is the single source of truth for the affect channel.

## 9. Submit correct code → pass feedback

Paste the refsol (copy from the YAML under
`content/drills/py4e/v1.0.0/course.yaml` for this drill) and submit.

**Expected.** Feedback turns green, text reads `"Чисто! Тест пройдено."`
The page auto-advances (or offers a "Наступний дрил" CTA) pointing at
the second drill in ch01. The `drill_attempts` row gets written — you
can verify with `docker exec opentutor-api psql -c "SELECT COUNT(*)
FROM drill_attempts WHERE user_id=<your id>;"`.

**If fails.** If the runner says PASS but the pill doesn't increment
on reload (step 10), check that `submit_drill` is committing the
session (`drill_submission.py:154` — `await db.commit()`).

## 10. Reload `/` — pill shows "пройдено: 1 / 191"

Navigate back to the dashboard and hard-reload (Ctrl-Shift-R).

**Expected.** The pill's second line now reads `пройдено: 1 / 191`
(or higher if you submitted more than one drill). The kick-off tail
(`— почни з будь-якого`) is gone once at least one drill is passed.

**If fails.** Dashboard pill didn't refresh → client cache staleness
(check SWR / react-query keys for `listDrillCourses`). Or the
`passed_count` query in `routers/drills.py::list_courses` grouped by
the wrong key — re-run the backend test
`test_list_courses_returns_passed_count` and trace from there.

---

## Exit criteria

- All 10 steps land on "Expected" without running an "If fails" branch.
- No red-X glyph / punitive copy anywhere in the flow.
- Browser console clean during the submit→pass path (no React key
  warnings, no 401s, no aborted requests).

If a step fails and the "If fails" branch doesn't cover it, freeze
GATE-1 and file a bug citing the step number. Do not advance to the
next phase until all ten are green.
