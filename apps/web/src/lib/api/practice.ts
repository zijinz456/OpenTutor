import { request } from "./client";

import type { GeneratedBatchSummaryBase, JsonObject, SavedGeneratedAsset } from "./client";

// ── Wrong Answers ──

interface WrongAnswerDetail {
  category?: string;
  confidence?: number;
  evidence?: string;
  related_concept?: string;
  diagnosis?: string;
  original_correct?: boolean;
  clean_correct?: boolean;
  diagnostic_problem_id?: string;
}

interface RetryWrongAnswerResult {
  is_correct: boolean;
  correct_answer: string | null;
  explanation: string | null;
}

export interface DerivedQuestionResult {
  problem_id: string;
  original_problem_id?: string;
  question: string;
  question_type: string;
  options: Record<string, string> | null;
  correct_answer: string | null;
  explanation: string | null;
  is_diagnostic?: boolean;
  simplifications_made?: string[];
  core_concept_preserved?: string;
}

interface WrongAnswerDiagnosisResult {
  diagnosis?: string;
  original_correct?: boolean;
  clean_correct?: boolean | null;
  interpretation?: string;
  status?: string;
  diagnostic_problem_id?: string;
  message?: string;
}

export interface WrongAnswerStats {
  total: number;
  mastered: number;
  unmastered: number;
  by_category: Record<string, number>;
  by_diagnosis: Record<string, number>;
}

export interface WrongAnswer {
  id: string;
  problem_id: string;
  question: string | null;
  question_type: string | null;
  options: Record<string, string> | null;
  user_answer: string;
  correct_answer: string | null;
  explanation: string | null;
  error_category: string | null;
  diagnosis: string | null;
  error_detail: WrongAnswerDetail | null;
  knowledge_points: string[] | null;
  review_count: number;
  mastered: boolean;
  created_at?: string | null;
}

export async function listWrongAnswers(
  courseId: string,
  params?: { mastered?: boolean; error_category?: string },
): Promise<WrongAnswer[]> {
  const search = new URLSearchParams();
  if (params?.mastered !== undefined) search.set("mastered", String(params.mastered));
  if (params?.error_category) search.set("error_category", params.error_category);
  const qs = search.toString();
  return request(`/wrong-answers/${courseId}${qs ? `?${qs}` : ""}`);
}

export async function retryWrongAnswer(id: string, userAnswer: string) {
  return request<RetryWrongAnswerResult>(
    `/wrong-answers/${id}/retry`,
    { method: "POST", body: JSON.stringify({ user_answer: userAnswer }) },
  );
}

export async function deriveQuestion(id: string) {
  return request<DerivedQuestionResult>(
    `/wrong-answers/${id}/derive`,
    { method: "POST" },
  );
}

export async function diagnoseWrongAnswer(id: string): Promise<WrongAnswerDiagnosisResult> {
  return request(`/wrong-answers/${id}/diagnose`, {
    method: "POST",
  });
}

export async function getWrongAnswerStats(courseId: string): Promise<WrongAnswerStats> {
  return request(`/wrong-answers/${courseId}/stats`);
}

// ── Quiz ──

export interface QuizProblem {
  id: string;
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  order_index: number;
  difficulty_layer?: number | null;
  problem_metadata?: Record<string, unknown> | null;
}

export interface GeneratedQuizBatchSummary {
  batch_id: GeneratedBatchSummaryBase["batch_id"];
  title: GeneratedBatchSummaryBase["title"];
  current_version: GeneratedBatchSummaryBase["current_version"];
  problem_count: number;
  is_active: GeneratedBatchSummaryBase["is_active"];
  updated_at: GeneratedBatchSummaryBase["updated_at"];
}

export interface GeneratedAssetBatchSummary extends GeneratedBatchSummaryBase {
  asset_count: number;
  preview: JsonObject;
}

export interface PrerequisiteGap {
  concept: string;
  concept_id: string;
  mastery: number;
  gap_severity: number;
}

export interface AnswerResult {
  is_correct: boolean;
  correct_answer: string | null;
  explanation: string | null;
  prerequisite_gaps?: PrerequisiteGap[] | null;
  warnings?: string[];
}

export interface QuizNodeFailure {
  node_id?: string | null;
  title: string;
  reason: string;
  discarded_count: number;
  errors: string[];
}

export interface ExtractQuizResult {
  status: string;
  problems_created: number;
  validated_count: number;
  repaired_count: number;
  discarded_count: number;
  node_failures: QuizNodeFailure[];
  warnings: string[];
}

export interface SavedGeneratedQuizBatch {
  saved: number;
  problem_ids: string[];
  batch_id: string;
  version: number;
  replaced: boolean;
  discarded_count?: number;
  warnings?: string[];
}

export async function extractQuiz(
  courseId: string,
  contentNodeId?: string,
  mode?: string,
  difficulty?: "easy" | "medium" | "hard",
): Promise<ExtractQuizResult> {
  return request("/quiz/extract", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      content_node_id: contentNodeId,
      mode,
      difficulty,
    }),
  });
}

export async function listProblems(courseId: string): Promise<QuizProblem[]> {
  return request(`/quiz/${courseId}`);
}

export async function listGeneratedQuizBatches(courseId: string): Promise<GeneratedQuizBatchSummary[]> {
  return request(`/quiz/${courseId}/generated-batches`);
}

export async function saveGeneratedQuiz(
  courseId: string,
  rawContent: string,
  title?: string,
  replaceBatchId?: string,
): Promise<SavedGeneratedQuizBatch> {
  return request("/quiz/save-generated", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      raw_content: rawContent,
      title,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function submitAnswer(problemId: string, answer: string, answerTimeMs?: number): Promise<AnswerResult> {
  return request("/quiz/submit", {
    method: "POST",
    body: JSON.stringify({ problem_id: problemId, user_answer: answer, answer_time_ms: answerTimeMs }),
  });
}

// ── Daily Session (ADHD UX §8, Phase 13) ──

/**
 * One card in the ADHD daily-session response.
 *
 * Mirrors the `DailyPlanCard` Pydantic schema at
 * `apps/api/schemas/sessions.py`. The field set is a deliberate subset of
 * `QuizProblem` so the same renderer dispatches on `question_type` — see
 * the render branches in `app/session/daily/page.tsx`.
 */
export interface DailyPlanCard {
  id: string;
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  correct_answer: string | null;
  explanation: string | null;
  difficulty_layer: number | null;
  content_node_id: string | null;
  problem_metadata: Record<string, unknown> | null;
}

/** Allowed session sizes — MASTER §12 + plan/adhd_ux_phase13.md §Q2. */
export type DailySessionSize = 1 | 5 | 10;
export type DailyPlanStrategy = "adhd_safe" | "easy_only";
export type DailyPlanReason = "nothing_due" | "bad_day_empty";

export interface DailyPlan {
  cards: DailyPlanCard[];
  size: number;
  /** Empty-pool hint for the dashboard CTA. `bad_day_empty` is the
   *  softer bad-day branch where the filter found no eligible easy cards. */
  reason: DailyPlanReason | null;
}

interface GetDailyPlanOptions {
  strategy?: DailyPlanStrategy;
}

export async function getDailyPlan(
  size: DailySessionSize,
  options?: GetDailyPlanOptions,
): Promise<DailyPlan> {
  const params = new URLSearchParams({ size: String(size) });
  if (options?.strategy) {
    params.set("strategy", options.strategy);
  }
  return request(`/sessions/daily-plan?${params.toString()}`);
}

// ── Brutal Drill (Phase 6) ──

/** Allowed Brutal batch sizes — mirrors `BrutalSessionSize` on the server
 *  (`schemas/sessions.py`). Interview-prep profile; see
 *  `plan/brutal_drill_mode_phase6.md` §Architecture. */
export type BrutalSessionSize = 20 | 30 | 50;

/** Per-card timeout (seconds) surfaced to the CTA picker. Mirrors
 *  `BrutalTimeoutSeconds` on the server. */
export type BrutalTimeoutSeconds = 15 | 30 | 60;

/**
 * Response body for `GET /api/sessions/brutal-plan`.
 *
 * Reuses {@link DailyPlanCard} so the same MC renderer handles both
 * daily and brutal card bodies. Notable differences vs {@link DailyPlan}:
 *
 * - `strategy` is pinned to `"struggle_first"` — the only selector the
 *   brutal endpoint exposes. Present as a field (not a silent default)
 *   so UI copy can surface the mode without a second round-trip.
 * - `warning === "pool_small"` fires when the pool couldn't fill the
 *   requested size. The daily endpoint swallows partial fills because
 *   ADHD flow accepts short decks; Brutal users opted into a heavy
 *   batch on purpose, so the frontend surfaces a confirm modal.
 * - There is NO `reason` field. Empty cards + `warning === null` means
 *   "nothing to drill" — the frontend renders the closure screen.
 */
export interface BrutalPlanResponse {
  cards: DailyPlanCard[];
  size: number;
  strategy: "struggle_first";
  warning: "pool_small" | null;
}

export async function getBrutalPlan(
  size: BrutalSessionSize,
): Promise<BrutalPlanResponse> {
  return request(`/sessions/brutal-plan?size=${size}`);
}

// ── Flashcards ──

interface FlashcardFsrsState {
  difficulty: number;
  stability: number;
  reps: number;
  lapses: number;
  state: string;
  due: string | null;
  last_review?: string | null;
}

interface FlashcardReviewResult {
  card: Flashcard;
  next_review: string | null;
}

export interface DueFlashcardsResult {
  cards: Flashcard[];
  due_count: number;
  total_batches: number;
}

export interface Flashcard {
  id: string;
  front: string;
  back: string;
  difficulty: string;
  fsrs: FlashcardFsrsState;
  course_id?: string;
  batch_id?: string;
}

export async function generateFlashcards(
  courseId: string,
  count: number = 5,
  mode?: string,
): Promise<{ cards: Flashcard[]; count: number }> {
  return request("/flashcards/generate", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId, count, mode }),
  });
}

export async function saveGeneratedFlashcards(
  courseId: string,
  cards: Flashcard[],
  title?: string,
  replaceBatchId?: string,
): Promise<SavedGeneratedAsset> {
  return request("/flashcards/generated/save", {
    method: "POST",
    body: JSON.stringify({
      course_id: courseId,
      cards,
      title,
      replace_batch_id: replaceBatchId,
    }),
  });
}

export async function listGeneratedFlashcardBatches(courseId: string): Promise<GeneratedAssetBatchSummary[]> {
  return request(`/flashcards/generated/${courseId}`);
}

export async function reviewFlashcard(
  card: Flashcard,
  rating: number,
): Promise<FlashcardReviewResult> {
  return request("/flashcards/review", {
    method: "POST",
    body: JSON.stringify({ card, rating }),
  });
}

export async function getDueFlashcards(
  courseId: string,
): Promise<DueFlashcardsResult> {
  return request(`/flashcards/due/${courseId}`);
}

export interface LectorFlashcard extends Flashcard {
  card_index?: number;
  lector_priority?: number;
  lector_reason?: string;
}

export interface LectorOrderResult {
  cards: LectorFlashcard[];
  count: number;
  lector_concepts: number;
}

export async function getLectorOrderedFlashcards(
  courseId: string,
): Promise<LectorOrderResult> {
  return request(`/flashcards/lector-order/${courseId}`);
}

// ── Confusion Pairs ──

export interface ConfusionPair {
  concept_a: string;
  concept_b: string;
  weight: number;
  description_a?: string | null;
  description_b?: string | null;
}

export interface ConfusionPairsResult {
  pairs: ConfusionPair[];
  count: number;
}

export async function getConfusionPairs(courseId: string): Promise<ConfusionPairsResult> {
  return request(`/flashcards/confusion-pairs/${courseId}`);
}

// ── Wrong Answer Review ──

interface WrongAnswerReviewResult {
  review: string;
  wrong_answer_count: number;
  wrong_answer_ids: string[];
}

export async function getWrongAnswerReview(courseId: string): Promise<WrongAnswerReviewResult> {
  return request(`/workflows/wrong-answer-review?course_id=${courseId}`);
}
