/**
 * useRoomGenerationStream — React hook subscribing to the path-generation
 * SSE feed for one job_id (Phase 16b Bundle B).
 *
 * Backed by ``GET /api/paths/generate-room/stream/{job_id}`` shipped in
 * ``apps/api/routers/paths.py``. Each SSE message is JSON-encoded after
 * ``data:`` and carries a ``status`` value drawn from
 * ``queued|outline|tasks|persisting|completed|error``. The ``completed``
 * event also carries ``room_id`` + ``path_id``; ``error`` carries
 * ``error_code``.
 *
 * Returns a flat `StreamState` shape — the consumer modal renders a
 * progress bar from `progress`, navigates to `/tracks/{slug}/rooms/{id}`
 * once `roomId` is set, and surfaces `error.code` for known failure modes.
 *
 * EventSource is the simplest fit (no body, GET-only, browser-managed
 * reconnect). When `jobId` is null the hook does nothing — useful while
 * the parent is still awaiting the POST response.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type StreamStatus =
  | "idle"
  | "queued"
  | "outline"
  | "tasks"
  | "persisting"
  | "completed"
  | "error";

export type StreamProgress = 0 | 1 | 2 | 3 | 4;

export interface StreamError {
  code: string;
  message?: string;
}

export interface StreamState {
  status: StreamStatus;
  /** 0 queued · 1 outline · 2 tasks · 3 persisting · 4 completed. */
  progress: StreamProgress;
  roomId: string | null;
  pathId: string | null;
  error: StreamError | null;
}

/**
 * Hook return value — the {@link StreamState} flat fields plus a
 * `disconnect()` method that closes the underlying EventSource and
 * forces the hook into terminal `idle` state.
 *
 * Why a method? Closing on unmount + jobId-change is automatic, but
 * consumers (e.g. the modal) sometimes need to abort earlier — when
 * the user closes the modal manually, or chooses "Stay here" after
 * completion. Calling `disconnect()` is safe and idempotent.
 */
export interface StreamHandle extends StreamState {
  /**
   * Close the underlying EventSource immediately. Idempotent — safe
   * to call multiple times. After disconnect the hook returns idle
   * state until `jobId` changes.
   */
  disconnect: () => void;
}

const IDLE_STATE: StreamState = {
  status: "idle",
  progress: 0,
  roomId: null,
  pathId: null,
  error: null,
};

const PROGRESS_BY_STATUS: Record<Exclude<StreamStatus, "idle">, StreamProgress> = {
  queued: 0,
  outline: 1,
  tasks: 2,
  persisting: 3,
  completed: 4,
  error: 0,
};

interface RawEventPayload {
  status?: string;
  room_id?: string;
  path_id?: string;
  error_code?: string;
  message?: string;
}

function isStreamStatus(s: string | undefined): s is Exclude<StreamStatus, "idle"> {
  return (
    s === "queued" ||
    s === "outline" ||
    s === "tasks" ||
    s === "persisting" ||
    s === "completed" ||
    s === "error"
  );
}

/**
 * Subscribe to the SSE feed for `jobId`. Pass `null` to stay idle (e.g.
 * before the POST resolves). Cleans up the EventSource on unmount and
 * whenever `jobId` changes.
 *
 * Returns a {@link StreamHandle} — the flat state plus `disconnect()`
 * for callers that need to tear down early (e.g. modal closed by user
 * before the job finishes).
 */
export function useRoomGenerationStream(jobId: string | null): StreamHandle {
  const [state, setState] = useState<StreamState>(IDLE_STATE);

  // Hold a stable reference to the close-fn for the active EventSource.
  // Replaced on every effect run; null when there is no live connection.
  // We use a ref (not state) because flipping it must not re-render.
  const closeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!jobId) {
      setState(IDLE_STATE);
      closeRef.current = null;
      return;
    }

    // Reset for every new jobId — never carry over stale terminal state.
    setState({ ...IDLE_STATE, status: "queued" });

    // Some test environments / older browsers lack EventSource; bail
    // safely rather than crashing the component tree.
    if (typeof EventSource === "undefined") {
      setState({
        ...IDLE_STATE,
        status: "error",
        error: { code: "eventsource_unsupported" },
      });
      closeRef.current = null;
      return;
    }

    const url = `/api/paths/generate-room/stream/${encodeURIComponent(jobId)}`;
    const source = new EventSource(url, { withCredentials: true });
    let closed = false;

    const close = () => {
      if (closed) return;
      closed = true;
      source.close();
    };
    closeRef.current = close;

    const handleMessage = (evt: MessageEvent) => {
      let payload: RawEventPayload | null = null;
      try {
        payload = JSON.parse(evt.data) as RawEventPayload;
      } catch {
        // Ignore malformed event — backend always JSON-encodes; if we got
        // garbage there's no actionable update.
        return;
      }
      if (!payload || !isStreamStatus(payload.status)) return;

      const status = payload.status;

      if (status === "completed") {
        setState({
          status: "completed",
          progress: 4,
          roomId: payload.room_id ?? null,
          pathId: payload.path_id ?? null,
          error: null,
        });
        close();
        return;
      }

      if (status === "error") {
        setState({
          status: "error",
          progress: 0,
          roomId: null,
          pathId: null,
          error: {
            code: payload.error_code ?? "unknown",
            message: payload.message,
          },
        });
        close();
        return;
      }

      // Ordered intermediate status — update progress monotonically.
      setState((prev) => ({
        ...prev,
        status,
        progress: PROGRESS_BY_STATUS[status],
        error: null,
      }));
    };

    const handleError = () => {
      // EventSource auto-reconnects on transient drops; only treat as a
      // hard failure when readyState is CLOSED (server hung up cleanly
      // mid-stream without a terminal event).
      if (source.readyState === EventSource.CLOSED && !closed) {
        setState((prev) =>
          prev.status === "completed"
            ? prev
            : {
                ...prev,
                status: "error",
                error: prev.error ?? { code: "stream_disconnected" },
              },
        );
        close();
      }
    };

    source.addEventListener("message", handleMessage);
    source.addEventListener("error", handleError);

    return () => {
      source.removeEventListener("message", handleMessage);
      source.removeEventListener("error", handleError);
      close();
      closeRef.current = null;
    };
  }, [jobId]);

  // Stable wrapper exposed to consumers — closes the active EventSource
  // (if any) and forces the hook back to idle. Idempotent.
  const disconnect = useCallback(() => {
    if (closeRef.current) {
      closeRef.current();
      closeRef.current = null;
    }
    setState(IDLE_STATE);
  }, []);

  return { ...state, disconnect };
}
