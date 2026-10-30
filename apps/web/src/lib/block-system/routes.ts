import type { BlockType } from "./types";

/**
 * Canonical dedicated route for each block type. Blocks in the workspace grid
 * are summary cards that link here; the route is the full UI.
 */
const BLOCK_ROUTES: Partial<Record<BlockType, (courseId: string) => string>> = {
  notes: (courseId) => `/course/${courseId}/notes`,
  quiz: (courseId) => `/course/${courseId}/practice?tab=quiz`,
  flashcards: (courseId) => `/course/${courseId}/practice?tab=flashcards`,
  wrong_answers: (courseId) => `/course/${courseId}/practice?tab=mistakes`,
  review: (courseId) => `/course/${courseId}/review`,
  plan: (courseId) => `/course/${courseId}/plan`,
  progress: (courseId) => `/course/${courseId}/profile?tab=progress`,
  forecast: (courseId) => `/course/${courseId}/profile?tab=forecast`,
  knowledge_graph: (courseId) => `/course/${courseId}/profile?tab=graph`,
};

export function blockRouteHref(type: BlockType, courseId: string): string | null {
  return BLOCK_ROUTES[type]?.(courseId) ?? null;
}
