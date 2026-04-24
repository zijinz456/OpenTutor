/**
 * Drills — frontend client (Phase 16c practice-first pivot).
 *
 * Thin wrappers over the five read endpoints under ``/api/drills`` shipped
 * by ``apps/api/routers/drills.py``:
 *
 *   GET  /drills/courses                 → DrillCourseOut[]
 *   GET  /drills/courses/{slug}          → DrillCourseTOC
 *   GET  /drills/{drill_id}              → DrillOut
 *   POST /drills/{drill_id}/submit       → DrillSubmitResult
 *   GET  /drills/next?course_slug=…      → DrillOut | null (204)
 *
 * Notes
 * -----
 * * Uses the shared ``request()`` wrapper for retry/timeout/toast. 204
 *   responses resolve to ``undefined`` at the wrapper level — the
 *   ``getNextDrill`` helper normalises that to ``null`` for ergonomic
 *   callers.
 * * ``hidden_tests`` are deliberately absent from every payload shape
 *   below; the runner on the server never emits them and the UI must
 *   not rely on them.
 */
import { request } from "./client";

export interface DrillOut {
  id: string;
  slug: string;
  title: string;
  why_it_matters: string;
  starter_code: string;
  hints: string[];
  skill_tags: string[];
  source_citation: string;
  time_budget_min: number;
  difficulty_layer: number;
  order_index: number;
}

export interface DrillModuleTOC {
  id: string;
  slug: string;
  title: string;
  order_index: number;
  outcome: string | null;
  drill_count: number;
  drills: DrillOut[];
}

export interface DrillCourseOut {
  id: string;
  slug: string;
  title: string;
  source: string;
  version: string;
  description: string | null;
  estimated_hours: number | null;
  module_count: number;
}

export interface DrillCourseTOC extends DrillCourseOut {
  modules: DrillModuleTOC[];
}

export interface DrillSubmitResult {
  passed: boolean;
  runner_output: string;
  feedback: string | null;
  duration_ms: number;
  next_drill_id: string | null;
}

/** `GET /api/drills/courses` — all compiled courses, sans modules. */
export async function listDrillCourses(): Promise<DrillCourseOut[]> {
  return request("/drills/courses");
}

/** `GET /api/drills/courses/{slug}` — full TOC for one course. */
export async function getDrillCourseTOC(slug: string): Promise<DrillCourseTOC> {
  return request(`/drills/courses/${encodeURIComponent(slug)}`);
}

/** `GET /api/drills/{drill_id}` — single drill detail, no hidden tests. */
export async function getDrill(drillId: string): Promise<DrillOut> {
  return request(`/drills/${encodeURIComponent(drillId)}`);
}

/** `POST /api/drills/{drill_id}/submit` — run hidden tests, persist attempt. */
export async function submitDrill(
  drillId: string,
  submittedCode: string,
): Promise<DrillSubmitResult> {
  return request(`/drills/${encodeURIComponent(drillId)}/submit`, {
    method: "POST",
    body: JSON.stringify({ submitted_code: submittedCode }),
  });
}

/**
 * `GET /api/drills/next?course_slug=…` — next unpassed drill, or ``null``
 * when the course is done (API returns 204).
 *
 * The shared ``request()`` resolves 204 to ``undefined``; we normalise to
 * ``null`` so callers can use a simple truthy check.
 */
export async function getNextDrill(
  courseSlug: string,
): Promise<DrillOut | null> {
  const res = await request<DrillOut | undefined>(
    `/drills/next?course_slug=${encodeURIComponent(courseSlug)}`,
  );
  return res ?? null;
}
