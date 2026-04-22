import { request } from "./client";

// ── Roadmap ──

export interface RoadmapEntry {
  node_id: string;
  slug: string;
  topic: string;
  blurb: string | null;
  mastery_score: number;
  position: number;
}

export async function getCourseRoadmap(courseId: string): Promise<RoadmapEntry[]> {
  return request(`/courses/${courseId}/roadmap`);
}

// ── Card candidates ──

export interface CardCandidate {
  front: string;
  back: string;
  concept_slug?: string | null;
}

export interface CardCandidatesResponse {
  cards: CardCandidate[];
  reason?: string | null;
}

export async function getCardCandidates(
  sessionId: string,
  messageId: string,
): Promise<CardCandidatesResponse> {
  return request(
    `/courses/sessions/${sessionId}/messages/${messageId}/card-candidates`,
  );
}

export interface SaveCandidatesResponse {
  saved_problem_ids: string[];
  asset_id: string;
  count: number;
  warnings: string[];
}

export async function saveCardCandidates(
  courseId: string,
  candidates: CardCandidate[],
): Promise<SaveCandidatesResponse> {
  return request(`/courses/${courseId}/flashcards/save-candidates`, {
    method: "POST",
    body: JSON.stringify({ candidates }),
  });
}
