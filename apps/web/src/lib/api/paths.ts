/**
 * Learning Paths — frontend client (Phase 16a T4).
 *
 * Mirrors the four read-only endpoints shipped under ``/api/paths`` in
 * ``apps/api/routers/paths.py``:
 *
 *   GET  /paths                              → PathListResponse
 *   GET  /paths/orphans                      → OrphanListResponse
 *   GET  /paths/{slug}                       → PathDetailResponse
 *   GET  /paths/{slug}/rooms/{roomId}        → RoomDetailResponse
 *
 * Uses the shared ``request()`` wrapper (retry/timeout/toast) — same
 * pattern as ``practice.ts``. All four endpoints are idempotent GETs
 * against local data, so the automatic retry-on-5xx behaviour is safe.
 */
import { request } from "./client";

export type PathDifficulty = "beginner" | "intermediate" | "advanced";

export interface PathSummary {
  id: string;
  slug: string;
  title: string;
  difficulty: PathDifficulty;
  track_id: string;
  description: string | null;
  room_total: number;
  room_complete: number;
  task_total: number;
  task_complete: number;
  orphan_count: number;
}

export interface PathListResponse {
  paths: PathSummary[];
  orphan_count: number;
}

export interface RoomSummary {
  id: string;
  slug: string;
  title: string;
  room_order: number;
  task_total: number;
  task_complete: number;
  intro_excerpt: string | null;
}

export interface PathDetailResponse {
  id: string;
  slug: string;
  title: string;
  difficulty: PathDifficulty;
  track_id: string;
  description: string | null;
  rooms: RoomSummary[];
  room_total: number;
  room_complete: number;
}

export interface RoomTask {
  id: string;
  task_order: number | null;
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  is_complete: boolean;
  difficulty_layer: number | null;
}

export interface RoomDetailResponse {
  id: string;
  slug: string;
  title: string;
  room_order: number;
  intro_excerpt: string | null;
  path_id: string;
  path_slug: string;
  path_title: string;
  tasks: RoomTask[];
  task_total: number;
  task_complete: number;
}

export interface OrphanListResponse {
  count: number;
  sample: Record<string, unknown>[];
}

/** `GET /api/paths` — dashboard list with aggregate progress counters. */
export async function listPaths(): Promise<PathListResponse> {
  return request("/paths");
}

/** `GET /api/paths/{slug}` — single path + its rooms. */
export async function getPathDetail(slug: string): Promise<PathDetailResponse> {
  return request(`/paths/${encodeURIComponent(slug)}`);
}

/** `GET /api/paths/{slug}/rooms/{roomId}` — single room + its tasks. */
export async function getRoomDetail(
  pathSlug: string,
  roomId: string,
): Promise<RoomDetailResponse> {
  return request(
    `/paths/${encodeURIComponent(pathSlug)}/rooms/${encodeURIComponent(roomId)}`,
  );
}

/** `GET /api/paths/orphans` — count + sample of unmapped cards. */
export async function listOrphans(): Promise<OrphanListResponse> {
  return request("/paths/orphans");
}
