# Close All Incomplete Flows — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close every incomplete logic loop identified in the OpenTutor audit — connect unreachable features, surface silent errors, remove dead code, and add missing UI entry points.

**Architecture:** 13 independent fixes across frontend (Next.js 16 / React 19) and backend (FastAPI / Python 3.14). Each task is self-contained and can be implemented in any order. Frontend uses `useT()`/`useTF()` i18n hooks; backend uses SQLAlchemy async + asyncpg.

**Tech Stack:** Next.js 16, React 19, Tailwind 4, Zustand, FastAPI, SQLAlchemy async, SSE streaming

---

## Task Overview

| # | Issue | Severity | Area | Effort |
|---|-------|----------|------|--------|
| 1 | Guided Sessions — no frontend entry point | High | FE+BE | Medium |
| 2 | `/analytics` route unreachable from nav | High | FE | Tiny |
| 3 | Template/Mode locale helpers unused | Medium | FE | Small |
| 4 | Quiz submit error silently swallowed | Medium | FE | Small |
| 5 | Flashcard view missing error/empty states | Medium | FE | Small |
| 6 | Canvas download silent failures | Medium | BE | Small |
| 7 | Auto-generation silent failures | Medium | BE | Small |
| 8 | Session count no dedup | Low | FE | Tiny |
| 9 | StudyPlan write-only (never read back) | Medium | BE+FE | Medium |
| 10 | StudyHabitLog orphaned model — delete | Low | BE | Tiny |
| 11 | Quiz endpoint missing pagination | Low | BE | Small |
| 12 | `searchContent` unused export — delete | Low | FE | Tiny |
| 13 | Ambient monitor disabled — enable with guard | Low | BE | Tiny |

---

## Task 1: Guided Sessions — Frontend Entry Point

The backend has a complete 4-phase guided learning loop (`guided_session.py`, 337 lines) with warmup → teach → practice → summary phases. The activity engine prepares sessions via `prepare_guided_session()`. But the frontend has **no button or UI** to trigger `[GUIDED_SESSION:start:task_id]`.

**Files:**
- Modify: `apps/web/src/components/sections/plan/activity-view.tsx`
- Modify: `apps/web/src/store/chat.ts`
- Modify: `apps/web/src/locales/en.json`
- Modify: `apps/web/src/locales/zh.json`

**Step 1: Read existing activity-view component**

Read `apps/web/src/components/sections/plan/activity-view.tsx` to understand how activity tasks are rendered. The activity engine returns tasks with `task_type: "guided_session"` — find where task cards are rendered.

**Step 2: Add i18n keys for guided session UI**

Add to `en.json`:
```json
"guidedSession.start": "Start Guided Session",
"guidedSession.resume": "Resume Session",
"guidedSession.phase": "Phase {current} of {total}",
"guidedSession.warmup": "Warmup",
"guidedSession.teach": "Learn",
"guidedSession.practice": "Practice",
"guidedSession.summary": "Summary"
```

Add equivalent Chinese translations to `zh.json`.

**Step 3: Add guided session button to activity view**

In the activity task card renderer, when `task.task_type === "guided_session"`:
- Render a prominent CTA button with `t("guidedSession.start")` or `t("guidedSession.resume")` depending on task status
- On click, send a chat message: `[GUIDED_SESSION:start:${task.id}]` via the chat store's `sendMessage()`

```tsx
// Inside the task card for guided_session type:
const handleStartSession = () => {
  const action = task.status === "paused" ? "resume" : "start";
  sendMessage(courseId, `[GUIDED_SESSION:${action}:${task.id}]`);
};

<button
  type="button"
  onClick={handleStartSession}
  className="px-4 py-2 rounded-xl bg-brand text-brand-foreground text-sm font-medium hover:opacity-90 transition-opacity"
>
  {task.status === "paused" ? t("guidedSession.resume") : t("guidedSession.start")}
</button>
```

**Step 4: Verify chat store can send guided session messages**

Read `apps/web/src/store/chat.ts` and confirm `sendMessage()` can be called externally from activity-view. If the chat store is not accessible from plan section, import and call it directly via `useChatStore.getState().sendMessage()`.

**Step 5: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors, guided session button visible in activity view for guided_session tasks.

**Step 6: Commit**

```bash
git add apps/web/src/components/sections/plan/activity-view.tsx apps/web/src/store/chat.ts apps/web/src/locales/en.json apps/web/src/locales/zh.json
git commit -m "feat: add frontend entry point for guided learning sessions"
```

---

## Task 2: Link `/analytics` Route from Navigation

The analytics page exists at `/course/[id]/profile/` with 7 tabs, but no navigation link points to it.

**Files:**
- Modify: `apps/web/src/components/shell/workspace-header.tsx`
- Modify: `apps/web/src/locales/en.json`
- Modify: `apps/web/src/locales/zh.json`

**Step 1: Read workspace-header**

Read `apps/web/src/components/shell/workspace-header.tsx` — the right nav section is at lines 97-124 with existing links (mode selector, search, notifications, settings).

**Step 2: Add i18n key**

Add to `en.json`: `"nav.analytics": "Analytics"`
Add to `zh.json`: `"nav.analytics": "数据分析"`

**Step 3: Add analytics link to header**

Add a `<Link>` to `/course/${courseId}/profile` in the right nav section, between NotificationBell and Settings link. Use `BarChart3` icon from lucide-react (already in the project).

```tsx
<Link
  href={`/course/${courseId}/profile`}
  className="p-2 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
  title={t("nav.analytics")}
>
  <BarChart3 className="size-4" />
</Link>
```

**Step 4: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors.

**Step 5: Commit**

```bash
git add apps/web/src/components/shell/workspace-header.tsx apps/web/src/locales/en.json apps/web/src/locales/zh.json
git commit -m "feat: add analytics link to workspace header navigation"
```

---

## Task 3: Wire Template/Mode Locale Helpers to UI

`templates.ts` exports `getTemplateName()`, `getTemplateDescription()`, `getModeName()`, `getModeDescription()` but `mode-selector.tsx` uses hardcoded `t(\`mode.${m.id}\`)` patterns instead.

**Files:**
- Modify: `apps/web/src/lib/block-system/templates.ts` — remove unused helpers
- No other changes needed

**Step 1: Assess the two approaches**

The mode-selector uses `t(\`mode.${m.id}\`)` which is the **correct** i18n approach (centralized locale files). The template helpers use `nameZh`/`name` fields which is a parallel, redundant system.

**Decision:** Delete the 4 unused helper functions (`getTemplateName`, `getTemplateDescription`, `getModeName`, `getModeDescription`) from `templates.ts` since the i18n system (`useT()`) is the canonical approach. Keep the `nameZh`/`name` fields on the types for backward compat but mark them as deprecated with a comment.

**Step 2: Remove unused functions**

Delete lines for `getTemplateName()`, `getTemplateDescription()`, `getModeName()`, `getModeDescription()` from `templates.ts`.

**Step 3: Verify no imports break**

Run: `cd apps/web && npx next build`
Expected: 0 errors (no file imports these functions).

**Step 4: Commit**

```bash
git add apps/web/src/lib/block-system/templates.ts
git commit -m "chore: remove unused template/mode locale helpers (i18n system is canonical)"
```

---

## Task 4: Surface Quiz Submit Errors

`quiz-view.tsx:125` catches `submitAnswer()` failures silently — user sees nothing.

**Files:**
- Modify: `apps/web/src/components/sections/practice/quiz-view.tsx`
- Modify: `apps/web/src/locales/en.json`
- Modify: `apps/web/src/locales/zh.json`

**Step 1: Read quiz-view.tsx**

Read `apps/web/src/components/sections/practice/quiz-view.tsx` focusing on the `handleOptionClick` function (lines 89-130) and existing error state patterns.

**Step 2: Add i18n keys**

Add to `en.json`: `"quiz.submitFailed": "Failed to submit answer. Please try again."`
Add to `zh.json`: `"quiz.submitFailed": "提交答案失败，请重试。"`

**Step 3: Add error state and display**

Add a `submitError` state variable and show it inline when set:

```tsx
const [submitError, setSubmitError] = useState<string | null>(null);

// In handleOptionClick catch block (line 125):
catch {
  setSubmitError(t("quiz.submitFailed"));
  setSelectedOption(null);
}

// Clear error when user selects new option:
// At start of handleOptionClick:
setSubmitError(null);
```

Add error display near the options area:

```tsx
{submitError && (
  <p className="text-xs text-destructive mt-2">{submitError}</p>
)}
```

**Step 4: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors.

**Step 5: Commit**

```bash
git add apps/web/src/components/sections/practice/quiz-view.tsx apps/web/src/locales/en.json apps/web/src/locales/zh.json
git commit -m "fix: surface quiz submission errors instead of swallowing silently"
```

---

## Task 5: Add Flashcard Error/Empty States

`flashcard-view.tsx` has multiple silent catches and no error messaging.

**Files:**
- Modify: `apps/web/src/components/sections/practice/flashcard-view.tsx`
- Modify: `apps/web/src/locales/en.json`
- Modify: `apps/web/src/locales/zh.json`

**Step 1: Read flashcard-view.tsx**

Read the full file, focusing on: `fetchData()` error handling (~line 56-57), `reviewFlashcard` catch (~line 141), and empty state rendering (~lines 160-177).

**Step 2: Add i18n keys**

```json
// en.json
"flashcard.loadFailed": "Failed to load flashcards. Please try again.",
"flashcard.reviewFailed": "Failed to record review. Your progress may not be saved.",

// zh.json
"flashcard.loadFailed": "加载闪卡失败，请重试。",
"flashcard.reviewFailed": "记录复习失败，进度可能未保存。"
```

**Step 3: Add error state**

Add a `loadError` state variable. In the `fetchData()` catch block, set it instead of silently returning empty. Show inline error message with a retry button:

```tsx
const [loadError, setLoadError] = useState<string | null>(null);

// In fetchData catch:
catch {
  setLoadError(t("flashcard.loadFailed"));
}

// In reviewFlashcard catch:
catch {
  setReviewError(t("flashcard.reviewFailed"));
  // Still advance card — best-effort
}
```

Add error display:
```tsx
{loadError && (
  <div className="text-center space-y-2">
    <p className="text-sm text-destructive">{loadError}</p>
    <button type="button" onClick={() => { setLoadError(null); fetchData(); }}
      className="text-xs text-brand hover:underline">
      {t("common.retry")}
    </button>
  </div>
)}
```

**Step 4: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors.

**Step 5: Commit**

```bash
git add apps/web/src/components/sections/practice/flashcard-view.tsx apps/web/src/locales/en.json apps/web/src/locales/zh.json
git commit -m "fix: add error states for flashcard loading and review submission"
```

---

## Task 6: Surface Canvas Download Failures

`canvas_loader.py:663-668` logs download failures at debug level. Users can't know which files failed.

**Files:**
- Modify: `apps/api/services/ingestion/canvas_loader.py`
- Modify: `apps/api/services/ingestion/pipeline.py`

**Step 1: Read canvas_loader.py download function**

Read `apps/api/services/ingestion/canvas_loader.py` around lines 588-670 (`download_canvas_file()`).

**Step 2: Upgrade logging and return error metadata**

Change `logger.debug` to `logger.warning` for download failures. Return a structured result instead of just `None`:

```python
# In download_canvas_file():
# Change line ~663-664:
logger.warning("Canvas file download failed (HTTP %s): %s", status_code, filename)

# Change line ~666:
logger.warning("All download attempts failed for: %s", filename)
```

**Step 3: Track failed files in pipeline**

In `pipeline.py` around line 573-575, collect failed filenames into a list and log a summary at the end:

```python
failed_files: list[str] = []

# In the loop where downloads are attempted:
if not saved_path:
    failed_files.append(file_info.get("filename", "unknown"))
    logger.warning("Skipped Canvas file (download failed): %s", file_info.get("filename"))
    continue

# After the loop:
if failed_files:
    logger.warning(
        "Canvas ingestion: %d/%d files failed to download: %s",
        len(failed_files), total_files, ", ".join(failed_files[:10])
    )
```

**Step 4: Verify**

Run: `cd apps/api && python -c "from services.ingestion.canvas_loader import download_canvas_file; print('OK')"`
Expected: OK (import succeeds).

**Step 5: Commit**

```bash
git add apps/api/services/ingestion/canvas_loader.py apps/api/services/ingestion/pipeline.py
git commit -m "fix: surface Canvas file download failures with warning-level logging"
```

---

## Task 7: Surface Auto-Generation Failures

`auto_generation.py` swallows quiz/flashcard generation errors. Users see empty content with no explanation.

**Files:**
- Modify: `apps/api/services/ingestion/auto_generation.py`
- Modify: `apps/api/routers/notifications.py` (if notification system exists)

**Step 1: Read auto_generation.py**

Read `apps/api/services/ingestion/auto_generation.py` focusing on `auto_generate_quiz()` (~lines 280-335) and `auto_generate_flashcards()` (~lines 236-277).

**Step 2: Upgrade error logging**

Change `logger.warning` to `logger.error` for generation failures and include the exception:

```python
# In auto_generate_quiz() catch block (~line 333):
except Exception:
    logger.exception("Auto quiz generation failed for course %s", course_id)
    return 0

# In auto_generate_flashcards() catch block (~line 275):
except Exception:
    logger.exception("Auto flashcard generation failed for course %s", course_id)
    return 0
```

**Step 3: Add dedup guard logging**

When generation is skipped due to existing content, log at info level so it's visible:

```python
# In quiz dedup guard (~line 300):
logger.info("Skipping quiz generation: %d questions already exist for course %s", count, course_id)

# In flashcard dedup guard (~line 252):
logger.info("Skipping flashcard generation: batches already exist for course %s", course_id)
```

**Step 4: Verify**

Run: `cd apps/api && python -c "from services.ingestion.auto_generation import auto_generate_quiz; print('OK')"`
Expected: OK.

**Step 5: Commit**

```bash
git add apps/api/services/ingestion/auto_generation.py
git commit -m "fix: surface auto-generation failures with exception logging"
```

---

## Task 8: Dedup Session Count Recording

`recordSessionVisit()` in `learner-persona.ts` increments `totalSessions` on every `courseId` change, including page refreshes.

**Files:**
- Modify: `apps/web/src/lib/learner-persona.ts`

**Step 1: Read learner-persona.ts**

Read `apps/web/src/lib/learner-persona.ts` lines 64-90.

**Step 2: Add minimum interval guard**

Add a 30-minute minimum between session recordings:

```typescript
export function recordSessionVisit(): void {
  const now = new Date();
  const persona = getPersona();

  // Dedup: skip if last session was < 30 minutes ago
  if (persona.lastSessionAt) {
    const lastAt = new Date(persona.lastSessionAt);
    const diffMs = now.getTime() - lastAt.getTime();
    if (diffMs < 30 * 60 * 1000) return;
  }

  // ... rest of existing logic unchanged
}
```

**Step 3: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors.

**Step 4: Commit**

```bash
git add apps/web/src/lib/learner-persona.ts
git commit -m "fix: dedup session count with 30-minute minimum interval"
```

---

## Task 9: Expose StudyPlan Read-Back

`StudyPlan` is created by the planner agent but never queried from the DB — the plan block can't display persisted plans.

**Files:**
- Modify: `apps/api/routers/workflows.py` — add GET endpoint
- Create: `apps/api/schemas/study_plan.py` — response schema
- Modify: `apps/web/src/lib/api/progress.ts` — add fetch function
- Modify: `apps/web/src/components/sections/plan/plan-view.tsx` — display saved plans

**Step 1: Read existing plan-related code**

Read `apps/api/routers/workflows.py` to find `SaveStudyPlanRequest` and existing plan endpoints.
Read `apps/api/models/study_plan.py` to understand the model structure.
Read `apps/web/src/components/sections/plan/plan-view.tsx` to see current plan display.

**Step 2: Add response schema**

Create `apps/api/schemas/study_plan.py`:

```python
from pydantic import BaseModel
from datetime import datetime
import uuid

class StudyPlanResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str | None = None
    tasks: dict
    created_at: datetime

    class Config:
        from_attributes = True
```

**Step 3: Add GET endpoint**

In `apps/api/routers/workflows.py`, add:

```python
from models.study_plan import StudyPlan
from schemas.study_plan import StudyPlanResponse

@router.get("/courses/{course_id}/study-plans", response_model=list[StudyPlanResponse])
async def list_study_plans(
    course_id: uuid.UUID,
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StudyPlan)
        .where(StudyPlan.course_id == course_id, StudyPlan.user_id == user.id)
        .order_by(StudyPlan.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
```

**Step 4: Add frontend API function**

In `apps/web/src/lib/api/progress.ts`, add:

```typescript
export async function getStudyPlans(courseId: string, limit = 5): Promise<StudyPlanResponse[]> {
  const res = await apiFetch(`/workflows/courses/${courseId}/study-plans?limit=${limit}`);
  if (!res.ok) return [];
  return res.json();
}
```

**Step 5: Wire into plan-view**

In `plan-view.tsx`, fetch and display saved study plans. Read the file first to find the right insertion point.

**Step 6: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors.

**Step 7: Commit**

```bash
git add apps/api/routers/workflows.py apps/api/schemas/study_plan.py apps/web/src/lib/api/progress.ts apps/web/src/components/sections/plan/plan-view.tsx apps/web/src/locales/en.json apps/web/src/locales/zh.json
git commit -m "feat: expose saved study plans via API and display in plan view"
```

---

## Task 10: Delete Orphaned StudyHabitLog Model

`StudyHabitLog` model is defined but never written to or read from by any code.

**Files:**
- Delete: `apps/api/models/study_habit.py` (if it only contains this model)
- Modify: `apps/api/models/__init__.py` (remove import)

**Step 1: Verify no references**

Search the entire codebase for `StudyHabitLog` to confirm it's truly orphaned (only in model definition and __init__.py).

**Step 2: Remove model**

Delete the file or remove the class, and remove its import from `models/__init__.py`.

**Step 3: Verify**

Run: `cd apps/api && python -c "from models import *; print('OK')"`
Expected: OK.

**Step 4: Commit**

```bash
git add apps/api/models/
git commit -m "chore: remove orphaned StudyHabitLog model (never used)"
```

---

## Task 11: Add Quiz Endpoint Pagination

`quiz.py:230-240` `list_problems()` returns ALL problems with no limit/offset.

**Files:**
- Modify: `apps/api/routers/quiz.py`

**Step 1: Read quiz.py list_problems**

Read `apps/api/routers/quiz.py` lines 225-245.

**Step 2: Add pagination parameters**

```python
@router.get("/{course_id}", response_model=list[ProblemResponse])
async def list_problems(
    course_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PracticeProblem)
        .where(PracticeProblem.course_id == course_id)
        .where(PracticeProblem.is_diagnostic == False)
        .where(PracticeProblem.is_archived == False)
        .order_by(PracticeProblem.order_index)
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()
```

**Step 3: Verify**

Run: `cd apps/api && python -c "from routers.quiz import router; print('OK')"`
Expected: OK.

**Step 4: Commit**

```bash
git add apps/api/routers/quiz.py
git commit -m "feat: add pagination (limit/offset) to quiz list endpoint"
```

---

## Task 12: Remove Unused `searchContent` Export

`searchContent` in `apps/web/src/lib/api/index.ts:201-214` is exported but never imported.

**Files:**
- Modify: `apps/web/src/lib/api/index.ts`

**Step 1: Verify no usages**

Search for `searchContent` across the entire frontend to confirm zero usages.

**Step 2: Remove the function**

Delete the `searchContent` function definition from `index.ts`.

**Step 3: Build and verify**

Run: `cd apps/web && npx next build`
Expected: 0 errors.

**Step 4: Commit**

```bash
git add apps/web/src/lib/api/index.ts
git commit -m "chore: remove unused searchContent API export"
```

---

## Task 13: Enable Ambient Monitor with Guard

The ambient monitor is properly implemented and registered in the scheduler but disabled via config flag `ambient_monitor_enabled = False`.

**Files:**
- Modify: `apps/api/config.py`

**Step 1: Read config.py**

Read `apps/api/config.py` line ~79 to see the ambient_monitor_enabled setting.

**Step 2: Enable with documentation**

Change the default to `True`:

```python
ambient_monitor_enabled: bool = True
```

**Step 3: Verify the scheduler guard**

Read `apps/api/services/scheduler/engine.py` lines 248-269 to confirm the guard (`if not settings.ambient_monitor_enabled: return`) is still in place, so it can be disabled via env var `AMBIENT_MONITOR_ENABLED=false` if needed.

**Step 4: Verify**

Run: `cd apps/api && python -c "from config import settings; print('ambient_monitor_enabled:', settings.ambient_monitor_enabled)"`
Expected: `ambient_monitor_enabled: True`

**Step 5: Commit**

```bash
git add apps/api/config.py
git commit -m "feat: enable ambient learning monitor by default (env-overridable)"
```

---

## Execution Order (Recommended)

Independent tasks can be parallelized. Suggested batches:

**Batch 1 — Quick wins (Tasks 2, 3, 8, 10, 12, 13):**
All tiny/small, no dependencies. Can run in parallel.

**Batch 2 — Error surfacing (Tasks 4, 5, 6, 7):**
Frontend and backend error handling improvements. Independent of each other.

**Batch 3 — Features (Tasks 1, 9, 11):**
Larger tasks — guided sessions, study plan read-back, quiz pagination.

## Final Verification

After all tasks:
```bash
cd apps/web && npx next build   # Frontend: 0 errors
cd apps/api && python -c "from main import app; print('OK')"  # Backend: imports clean
```
