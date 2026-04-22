"use client";

/**
 * Course roadmap list — §14.5 v2.1 T7 minimum viable UI.
 *
 * Fetches the syllabus-derived roadmap from `GET /courses/{id}/roadmap`
 * and renders a plain unordered list of topics with inline mastery
 * percentages. When the course has no syllabus yet (empty list), the
 * component renders nothing so it does not crowd the page.
 */

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { getCourseRoadmap, type RoadmapEntry } from "@/lib/api/curriculum";

interface RoadmapListProps {
  courseId: string;
}

type RoadmapState =
  | { status: "loading" }
  | { status: "ready"; entries: RoadmapEntry[] }
  | { status: "error" };

export function RoadmapList({ courseId }: RoadmapListProps) {
  const [state, setState] = useState<RoadmapState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    getCourseRoadmap(courseId)
      .then((data) => {
        if (cancelled) return;
        setState({
          status: "ready",
          entries: Array.isArray(data) ? data : [],
        });
      })
      .catch((err) => {
        if (cancelled) return;
        // 404 (no syllabus yet) is treated as empty; other errors are
        // shown but do not crash the page.
        if (err instanceof ApiError && err.status === 404) {
          setState({ status: "ready", entries: [] });
        } else {
          setState({ status: "error" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (state.status === "loading") {
    return null;
  }

  if (state.status === "error") {
    return (
      <div
        data-testid="roadmap-list-error"
        className="text-xs text-muted-foreground"
      >
        Could not load roadmap.
      </div>
    );
  }

  const entries = state.entries;
  if (entries.length === 0) {
    return null;
  }

  return (
    <section
      data-testid="roadmap-list"
      aria-label="Course roadmap"
      className="rounded-md border border-border bg-card/40 px-4 py-3"
    >
      <h3 className="mb-2 text-sm font-semibold">Roadmap</h3>
      <ul className="space-y-1 text-sm">
        {entries.map((entry) => {
          const pct = Math.round((entry.mastery_score ?? 0) * 100);
          return (
            <li
              key={entry.node_id}
              data-testid={`roadmap-entry-${entry.slug}`}
              className="flex items-baseline justify-between gap-3"
            >
              <div className="min-w-0 flex-1">
                <span className="font-medium">{entry.topic}</span>
                {entry.blurb ? (
                  <span className="ml-2 text-xs text-muted-foreground">
                    {entry.blurb}
                  </span>
                ) : null}
              </div>
              <span
                aria-label={`Mastery ${pct} percent`}
                className="shrink-0 text-xs tabular-nums text-muted-foreground"
              >
                {pct}%
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
