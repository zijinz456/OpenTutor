/**
 * Hacking Labs (§34.6 Phase 12 — T4) — web-security lab API client.
 *
 * Thin adapter over the existing `/quiz/submit` envelope. A `lab_exercise`
 * answer is serialised as JSON into `SubmitAnswerRequest.user_answer`; the
 * backend router branch validates against `LabExerciseSubmitPayload` and
 * dispatches to `services.practice.lab_grader.grade_lab_proof`.
 *
 * We intentionally do NOT introduce a second /submit path — reuse keeps
 * progress tracking, wrong-answer surfacing, LOOM mastery updates, and
 * analytics consistent with every other question type. Only the payload
 * wire-format differs.
 *
 * The `LabGradeResult.confidence` field is declared for forward compatibility
 * with a future `AnswerResponse.confidence` surfacing: today the backend
 * stores the grader's self-reported confidence into `PracticeResult.user_answer`
 * but does NOT return it to the client. The `<LabExerciseBlock>` will render
 * the badge if-and-only-if the field arrives populated; until backend evolves,
 * the block renders without it. No UI regression today; no frontend change
 * needed tomorrow.
 */

import { submitAnswer } from "./practice";

/** Structured payload a user submits for a lab-exercise problem. */
export interface LabProof {
  /** Exact payload / attack input the user sent to the lab target. */
  payload_used: string;
  /** Flag string or prose description of observed post-exploitation behaviour. */
  flag_or_evidence: string;
  /** Optional localhost screenshot URL — backend rejects non-localhost URLs. */
  screenshot_url?: string;
}

/** Grader verdict surfaced to the UI after server-side rubric grading. */
export interface LabGradeResult {
  is_correct: boolean;
  /** Grader's one-line explanation of the verdict (rubric-derived). */
  explanation?: string;
  /**
   * Grader's self-reported confidence in [0, 1]. Not currently returned by
   * the backend `/quiz/submit` envelope — forward-compatible field; see
   * module doc-comment.
   */
  confidence?: number;
}

/**
 * Submit a lab proof-of-solve for grading.
 *
 * Wraps `submitAnswer(problemId, JSON.stringify(proof), answerTimeMs)` —
 * backend's `lab_exercise` branch (§34.6 T2) parses the JSON into
 * `LabExerciseSubmitPayload`, validates `screenshot_url` against
 * `^http://localhost:\d+(/|$)`, then grades via Groq rubric.
 *
 * The response envelope today (`AnswerResponse`) populates `is_correct` and
 * `explanation` (from the problem row — NOT the grader's rubric text; that is
 * stored into PracticeResult.ai_explanation for retrospective). See callers
 * for how they reconcile this.
 */
export async function submitLabProof(
  problemId: string,
  proof: LabProof,
  answerTimeMs?: number,
): Promise<LabGradeResult> {
  const serialized = JSON.stringify(proof);
  const res = await submitAnswer(problemId, serialized, answerTimeMs);
  return {
    is_correct: res.is_correct,
    explanation: res.explanation ?? undefined,
  };
}
