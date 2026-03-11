/**
 * useBlockEngagement — IntersectionObserver-based tracking of block visibility.
 *
 * Tracks how long a block is visible (>5s threshold) and batches
 * engagement events to the backend every 30 seconds.
 */

import { useEffect, useRef } from "react";
import { request, API_BASE, buildSecureRequestInit } from "@/lib/api/client";

interface EngagementEvent {
  block_type: string;
  event_type: string;
  duration_ms: number;
  course_id: string;
}

const eventBuffer: EngagementEvent[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;
let unloadListenerAdded = false;

const FLUSH_INTERVAL_MS = 30_000;
const VISIBILITY_THRESHOLD_MS = 5_000;
const STUDY_TIME_THRESHOLD_MS = 60_000; // 60s of focused time → study_time event

async function flushEvents(): Promise<void> {
  if (eventBuffer.length === 0) return;
  const batch = eventBuffer.splice(0);
  try {
    await request("/blocks/events", {
      method: "POST",
      body: JSON.stringify({ events: batch }),
    });
  } catch {
    // Best-effort: re-queue failed events (drop if buffer is huge)
    if (eventBuffer.length < 100) {
      eventBuffer.push(...batch);
    }
  }
}

/** Use fetch with keepalive on page hide — supports auth headers unlike sendBeacon. */
function flushEventsSync(): void {
  if (eventBuffer.length === 0) return;
  const batch = eventBuffer.splice(0);
  try {
    // keepalive: true allows the request to outlive the page, similar to sendBeacon
    // but with full header support for auth
    void fetch(`${API_BASE}/blocks/events`, {
      ...buildSecureRequestInit({
        method: "POST",
        includeJsonContentType: true,
        keepalive: true,
        body: JSON.stringify({ events: batch }),
      }),
    });
  } catch {
    // Best-effort
  }
}

function ensureFlushTimer(): void {
  if (flushTimer) return;
  flushTimer = setInterval(() => void flushEvents(), FLUSH_INTERVAL_MS);
  if (typeof window !== "undefined" && !unloadListenerAdded) {
    unloadListenerAdded = true;
    window.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") flushEventsSync();
    });
  }
}

export function useBlockEngagement(
  blockId: string,
  blockType: string,
  courseId: string,
): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement | null>(null);
  const visibleSince = useRef<number | null>(null);

  useEffect(() => {
    ensureFlushTimer();
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          visibleSince.current = Date.now();
        } else if (visibleSince.current) {
          const duration = Date.now() - visibleSince.current;
          visibleSince.current = null;
          if (duration >= VISIBILITY_THRESHOLD_MS) {
            eventBuffer.push({
              block_type: blockType,
              event_type: "view",
              duration_ms: duration,
              course_id: courseId,
            });
            // Extended focused time → study_time event for preference learning
            if (duration >= STUDY_TIME_THRESHOLD_MS) {
              eventBuffer.push({
                block_type: blockType,
                event_type: "study_time",
                duration_ms: duration,
                course_id: courseId,
              });
            }
          }
        }
      },
      { threshold: 0.5 },
    );

    observer.observe(el);
    return () => {
      observer.disconnect();
      // Record final duration on unmount
      if (visibleSince.current) {
        const duration = Date.now() - visibleSince.current;
        if (duration >= VISIBILITY_THRESHOLD_MS) {
          eventBuffer.push({
            block_type: blockType,
            event_type: "view",
            duration_ms: duration,
            course_id: courseId,
          });
          if (duration >= STUDY_TIME_THRESHOLD_MS) {
            eventBuffer.push({
              block_type: blockType,
              event_type: "study_time",
              duration_ms: duration,
              course_id: courseId,
            });
          }
        }
        visibleSince.current = null;
      }
    };
  }, [blockId, blockType, courseId]);

  return ref;
}

/**
 * Record a discrete block interaction event (approve, dismiss, manual add/remove).
 */
export function recordBlockEvent(
  courseId: string,
  blockType: string,
  eventType: "approve" | "dismiss" | "manual_add" | "manual_remove" | "effective_review",
): void {
  ensureFlushTimer();
  eventBuffer.push({
    block_type: blockType,
    event_type: eventType,
    duration_ms: 0,
    course_id: courseId,
  });
}
