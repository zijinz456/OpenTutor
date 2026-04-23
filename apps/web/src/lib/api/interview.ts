/**
 * Interviewer agent — frontend client (Phase 5 T6a).
 *
 * Backend contract: `POST /api/interview/*` (five endpoints, see
 * `apps/api/routers/interview.py`).
 *
 *   - POST   /interview/start                  → single JSON response
 *   - POST   /interview/{id}/answer            → SSE stream
 *   - GET    /interview/{id}                   → single JSON response
 *   - POST   /interview/{id}/abandon           → single JSON response
 *   - POST   /interview/{id}/save-gaps         → single JSON response
 *
 * The SSE `answer` stream follows the same `event: X\ndata: {...}\n\n`
 * envelope the chat route uses, so the parser here is a slimmed-down
 * version of the one in `chat.ts` — only three event types to handle,
 * no tool/provenance/action fan-out.
 *
 * We use a direct `fetch` (not `request`) for the streaming endpoint
 * since auto-retrying a half-consumed SSE body would reset rubric
 * and next-question side effects already persisted on the backend.
 * The non-streaming endpoints route through `request` for retry+CSRF.
 */

import { API_BASE, buildSecureRequestInit, parseApiError, request } from "./client";

// ---------------------------------------------------------------------------
// Shared domain types
// ---------------------------------------------------------------------------

export type InterviewMode =
  | "behavioral"
  | "technical"
  | "code_defense"
  | "mixed";

export type InterviewDuration = "quick" | "standard" | "deep";

export type InterviewStatus =
  | "in_progress"
  | "completed"
  | "completed_early"
  | "abandoned";

export interface DimensionScore {
  score: number;
  feedback: string;
}

export interface RubricScores {
  dimensions: Record<string, DimensionScore>;
  feedback_short: string;
}

export interface TurnResponse {
  id?: string;
  turn_number: number;
  question: string;
  question_type: string;
  grounding_source?: string | null;
  answer?: string | null;
  rubric?: RubricScores | null;
  answer_time_ms?: number | null;
}

export interface SummaryResponse {
  avg_by_dimension: Record<string, number>;
  weakest_dimensions: string[];
  worst_turn_id?: string | null;
  answer_time_ms_avg?: number | null;
  total_answer_time_s?: number | null;
}

export interface InterviewSessionState {
  session_id: string;
  status: InterviewStatus;
  mode: string;
  duration: string;
  project_focus: string;
  total_turns: number;
  completed_turns: number;
  turns: TurnResponse[];
  summary?: SummaryResponse | null;
}

// ---------------------------------------------------------------------------
// Start + CRUD
// ---------------------------------------------------------------------------

export interface InterviewStartRequest {
  project_focus: string;
  mode: InterviewMode;
  duration: InterviewDuration;
  course_id?: string | null;
}

export interface InterviewStartResponse {
  session_id: string;
  question: string;
  turn_number: number;
  total_turns: number;
  grounding_source: string;
}

/** `POST /interview/start`. Throws `ApiError` on 4xx/5xx. */
export async function startInterview(
  body: InterviewStartRequest,
): Promise<InterviewStartResponse> {
  return request<InterviewStartResponse>("/interview/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** `GET /interview/{id}` — full state rehydrate for pause+resume. */
export async function getInterviewSession(
  sessionId: string,
): Promise<InterviewSessionState> {
  return request<InterviewSessionState>(`/interview/${sessionId}`);
}

/** `POST /interview/{id}/abandon` — user pressed "End early". */
export async function abandonInterview(
  sessionId: string,
): Promise<InterviewSessionState> {
  return request<InterviewSessionState>(`/interview/${sessionId}/abandon`, {
    method: "POST",
  });
}

export interface SaveGapsResponse {
  saved_count: number;
  problem_ids: string[];
}

/** `POST /interview/{id}/save-gaps` — spawn gap flashcards. */
export async function saveInterviewGaps(
  sessionId: string,
  turnIds: string[],
): Promise<SaveGapsResponse> {
  return request<SaveGapsResponse>(`/interview/${sessionId}/save-gaps`, {
    method: "POST",
    body: JSON.stringify({ turn_ids: turnIds }),
  });
}

// ---------------------------------------------------------------------------
// SSE stream — POST /interview/{id}/answer
// ---------------------------------------------------------------------------

export type InterviewStreamEvent =
  | {
      event: "rubric";
      data: {
        turn_number: number;
        dimensions: Record<string, DimensionScore>;
        feedback_short: string;
      };
    }
  | {
      event: "next_question";
      data: {
        turn_number: number;
        question: string;
        question_type: string;
        grounding_source?: string;
      };
    }
  | {
      event: "completed";
      data: { session_id: string; summary: SummaryResponse };
    }
  | { event: "error"; data: { error: string } };

/**
 * Consume the SSE stream for a single answer submission.
 *
 * Backend emits `rubric` first (with grader scores + short feedback),
 * then either `next_question` (continues session) or `completed`
 * (inline-math summary, session done). The generator returns on
 * `completed` or `error`; the caller decides whether to surface the
 * error to the UI or retry.
 */
export async function* streamInterviewAnswer(
  sessionId: string,
  answerText: string,
  signal?: AbortSignal,
): AsyncGenerator<InterviewStreamEvent, void, unknown> {
  const res = await fetch(`${API_BASE}/interview/${sessionId}/answer`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: true,
      body: JSON.stringify({ answer_text: answerText }),
      signal,
    }),
  });

  if (!res.ok || !res.body) {
    throw await parseApiError(res);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEvent = "message";

  const findBoundary = (input: string): number => {
    const crlf = input.indexOf("\r\n\r\n");
    const lf = input.indexOf("\n\n");
    if (crlf === -1) return lf;
    if (lf === -1) return crlf;
    return Math.min(crlf, lf);
  };

  const parseBlock = (
    rawBlock: string,
  ): InterviewStreamEvent | null => {
    const block = rawBlock.replace(/\r/g, "");
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) {
        eventName = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        dataLines.push(line.slice(6));
      }
    }
    if (!dataLines.length) {
      lastEvent = eventName || lastEvent;
      return null;
    }
    const resolved = eventName || lastEvent;
    lastEvent = resolved;

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    } catch {
      return null;
    }

    if (resolved === "rubric") {
      return {
        event: "rubric",
        data: {
          turn_number: Number(data.turn_number),
          dimensions: (data.dimensions ?? {}) as Record<string, DimensionScore>,
          feedback_short: String(data.feedback_short ?? ""),
        },
      };
    }
    if (resolved === "next_question") {
      return {
        event: "next_question",
        data: {
          turn_number: Number(data.turn_number),
          question: String(data.question ?? ""),
          question_type: String(data.question_type ?? ""),
          grounding_source: data.grounding_source
            ? String(data.grounding_source)
            : undefined,
        },
      };
    }
    if (resolved === "completed") {
      return {
        event: "completed",
        data: {
          session_id: String(data.session_id ?? ""),
          summary: data.summary as SummaryResponse,
        },
      };
    }
    if (resolved === "error") {
      return {
        event: "error",
        data: { error: String(data.error ?? "interview stream error") },
      };
    }
    return null;
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundary = findBoundary(buffer);
    while (boundary !== -1) {
      const sepLen = buffer.slice(boundary, boundary + 4) === "\r\n\r\n" ? 4 : 2;
      const rawBlock = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + sepLen);
      const parsed = parseBlock(rawBlock);
      if (parsed) yield parsed;
      boundary = findBoundary(buffer);
    }

    if (done) {
      const trailing = buffer.trim();
      if (trailing) {
        const parsed = parseBlock(trailing);
        if (parsed) yield parsed;
      }
      break;
    }
  }
}
