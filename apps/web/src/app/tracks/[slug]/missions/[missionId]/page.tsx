"use client";

/**
 * `/tracks/[slug]/missions/[missionId]` — Slice 2 three-pane mission page.
 *
 * Layout
 * ------
 * At `xl` and up (>=1280px):
 *
 *   ┌─ MissionHeader ────────────────────────────────────────────────┐
 *   │ TaskSidebar (280) │ Content (fluid)        │ Practice (480)     │
 *   ├─────────────────── MissionProgressFooter ──────────────────────┤
 *
 * Below `xl`: the task sidebar collapses to a top accordion (<details>)
 * and Content + Practice stack in the right column. Mobile inherits
 * the same stacking — single column smoke only, no pixel work.
 *
 * Why `<TaskRenderer>` lives in the practice pane
 * -----------------------------------------------
 * Phase 11 Code Runner is not a single exportable `<CodeRunner>` —
 * it's `pyodide-runtime.ts` plus the per-type block renderers
 * (`code-exercise-block`, `lab-exercise-block`, `apply-block`, etc.).
 * `<TaskRenderer>` (from the Phase 16a runner) already dispatches on
 * `question_type` to the right block. Keeping it whole — in one pane —
 * avoids remounting Monaco between "question" and "editor" halves of
 * the UI, which historically caused cursor bugs.
 *
 * State ownership
 * ---------------
 * `currentTaskId` is local page state — defaults to the first non-complete
 * task, or the first task if all are done. Clicking in the sidebar swaps
 * which task renders in the practice pane. The `onCorrect` bump from
 * `<TaskRenderer>` optimistically flips the sidebar's `Done` state so the
 * user gets feedback without a refetch.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { getRoomDetail, type RoomDetailResponse } from "@/lib/api";
import type { RoomTask } from "@/lib/api/paths";
import { MissionHeader } from "@/components/mission/mission-header";
import { TaskSidebar } from "@/components/mission/task-sidebar";
import { CheckpointSection } from "@/components/mission/checkpoint-section";
import { MissionProgressFooter } from "@/components/mission/mission-progress-footer";
import { TaskRenderer } from "@/components/path/RoomTaskList";

function MissionPageContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const missionParam = params?.missionId;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam;
  const roomId = Array.isArray(missionParam) ? missionParam[0] : missionParam;

  const [data, setData] = useState<RoomDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  /** Optimistic per-render override — lets the sidebar flip to Done
   *  immediately on a correct answer without re-querying the API. */
  const [extraComplete, setExtraComplete] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!slug || !roomId) return;
    let cancelled = false;
    setLoading(true);
    getRoomDetail(slug, roomId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setExtraComplete(new Set());
        // Pick the first non-complete task as the initial current,
        // or the first task when everything is already done (the
        // user gets a sensible landing state rather than a blank pane).
        const firstOpen =
          res.tasks.find((t) => !t.is_complete)?.id ??
          res.tasks[0]?.id ??
          null;
        setCurrentTaskId(firstOpen);
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "Couldn't load mission. Retry?",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug, roomId]);

  // Tasks with optimistic completion overlay so the sidebar reflects
  // a just-answered task as Done before the next refetch.
  const enrichedTasks = useMemo<RoomTask[]>(() => {
    if (!data) return [];
    return data.tasks.map((t) =>
      extraComplete.has(t.id) ? { ...t, is_complete: true } : t,
    );
  }, [data, extraComplete]);

  const displayedComplete = useMemo(
    () => enrichedTasks.filter((t) => t.is_complete).length,
    [enrichedTasks],
  );

  const currentTask = useMemo(
    () =>
      currentTaskId
        ? enrichedTasks.find((t) => t.id === currentTaskId) ?? null
        : null,
    [enrichedTasks, currentTaskId],
  );

  const currentIdx = currentTask
    ? enrichedTasks.findIndex((t) => t.id === currentTask.id)
    : -1;

  const handleTaskCorrect = (taskId: string) => {
    setExtraComplete((prev) => {
      if (prev.has(taskId)) return prev;
      const next = new Set(prev);
      next.add(taskId);
      return next;
    });
  };

  const handlePrev = () => {
    if (currentIdx > 0) {
      setCurrentTaskId(enrichedTasks[currentIdx - 1].id);
    }
  };
  const handleNext = () => {
    if (currentIdx >= 0 && currentIdx < enrichedTasks.length - 1) {
      setCurrentTaskId(enrichedTasks[currentIdx + 1].id);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--bg-base,hsl(var(--background)))] py-6 px-4">
        <div
          className="mx-auto max-w-7xl space-y-6"
          data-testid="mission-page-loading"
        >
          <div className="h-8 w-80 rounded bg-muted/40 animate-pulse" />
          <div className="h-4 w-48 rounded bg-muted/40 animate-pulse" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[var(--bg-base,hsl(var(--background)))] py-6 px-4">
        <div
          role="alert"
          data-testid="mission-page-error"
          className="mx-auto max-w-3xl rounded-xl bg-destructive/5 px-5 py-4 text-sm text-destructive"
        >
          {error}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const progressPct =
    data.task_total > 0
      ? Math.round((displayedComplete / data.task_total) * 100)
      : 0;

  return (
    <div
      className="min-h-screen bg-[var(--bg-base,hsl(var(--background)))] pb-20"
      data-testid="mission-page"
    >
      <div className="mx-auto max-w-7xl px-4 pt-4 space-y-4">
        <MissionHeader
          pathSlug={data.path_slug}
          pathTitle={data.path_title}
          missionTitle={data.title}
          difficulty={data.difficulty}
          etaMinutes={data.eta_minutes}
          moduleLabel={data.module_label}
        />

        {/* Below xl: sidebar collapses into a top accordion. Default-open
            on lg- and collapsed below so the narrow viewport doesn't
            push the content off-screen. */}
        <details
          className="xl:hidden rounded-md border border-[var(--border-subtle,rgba(255,255,255,0.06))] p-2"
          open
          data-testid="mission-page-tasks-accordion"
        >
          <summary className="cursor-pointer text-sm font-medium px-2 py-1">
            Tasks ({displayedComplete}/{data.task_total})
          </summary>
          <div className="mt-2">
            <TaskSidebar
              tasks={enrichedTasks}
              currentTaskId={currentTaskId}
              capstoneIds={data.capstone_problem_ids}
              onSelect={setCurrentTaskId}
            />
          </div>
        </details>

        <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_480px]">
          {/* Left rail — only visible at xl+ (below, the accordion above
              handles the list). Hidden here to avoid duplicate testids. */}
          <div className="hidden xl:block">
            <TaskSidebar
              tasks={enrichedTasks}
              currentTaskId={currentTaskId}
              capstoneIds={data.capstone_problem_ids}
              onSelect={setCurrentTaskId}
            />
          </div>

          {/* Middle pane — lesson prose + checkpoint launcher. Static
              across task switches, unlike the practice pane. */}
          <section
            data-testid="mission-content-pane"
            className="space-y-4 min-w-0"
          >
            <div>
              <div className="text-[11px] uppercase tracking-[0.04em] text-[var(--text-muted)]">
                {currentIdx >= 0
                  ? `Task ${currentIdx + 1} of ${enrichedTasks.length}`
                  : `${enrichedTasks.length} tasks`}
              </div>
              <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
                {data.title}
              </h1>
              {data.intro_excerpt ? (
                <p
                  data-testid="mission-intro-excerpt"
                  className="mt-2 text-sm leading-relaxed text-[var(--text-secondary,hsl(var(--muted-foreground)))]"
                >
                  {data.intro_excerpt}
                </p>
              ) : null}
            </div>

            <CheckpointSection
              capstoneIds={data.capstone_problem_ids}
              tasks={enrichedTasks}
              onSelect={setCurrentTaskId}
            />
          </section>

          {/* Right pane — interactive TaskRenderer. On xl+, this sits
              in its own column; below xl, it stacks under the content
              pane (grid collapses to 1 column). */}
          <section
            data-testid="mission-practice-pane"
            className="min-w-0 rounded-xl border border-[var(--border-subtle,rgba(255,255,255,0.06))] bg-card p-4"
          >
            {currentTask ? (
              <div className="space-y-3">
                <div className="text-[11px] uppercase tracking-[0.04em] text-[var(--text-muted)]">
                  Practice
                </div>
                <p className="text-sm font-medium text-foreground">
                  {currentTask.question}
                </p>
                <TaskRenderer
                  task={currentTask}
                  onCorrect={() => handleTaskCorrect(currentTask.id)}
                />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No tasks in this mission yet.
              </p>
            )}
          </section>
        </div>
      </div>

      <MissionProgressFooter
        progressPct={progressPct}
        etaMinutes={data.eta_minutes}
        canPrev={currentIdx > 0}
        canNext={currentIdx >= 0 && currentIdx < enrichedTasks.length - 1}
        onPrev={handlePrev}
        onNext={handleNext}
      />
    </div>
  );
}

export default function MissionPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <MissionPageContent />
    </Suspense>
  );
}
