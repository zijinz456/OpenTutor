"use client";

import { useCallback, useEffect, useRef } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { updateCourseLayout } from "@/lib/api";
import type { LearningMode } from "@/lib/block-system/types";
import { buildLayoutFromMode } from "@/lib/block-system/templates";

export function useBlockPersistence(
  courseId: string,
  course: { metadata?: unknown } | null,
) {
  const blocks = useWorkspaceStore((s) => s.spaceLayout.blocks);
  const loadBlocks = useWorkspaceStore((s) => s.loadBlocks);
  const blocksInitialized = useRef(false);
  const lastCourseIdRef = useRef<string | null>(null);
  const persistTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const flushLayout = useCallback(() => {
    if (!blocksInitialized.current) return;
    const layout = useWorkspaceStore.getState().spaceLayout;
    try { localStorage.setItem(`opentutor_blocks_${courseId}`, JSON.stringify(layout)); } catch { /* quota */ }
    updateCourseLayout(courseId, layout).catch((e) => console.error("[Course] layout persist failed:", e));
  }, [courseId]);

  useEffect(() => {
    if (lastCourseIdRef.current !== courseId) {
      lastCourseIdRef.current = courseId;
      blocksInitialized.current = false;
    }
    if (blocksInitialized.current) return;

    // Try localStorage first (always available)
    const saved = localStorage.getItem(`opentutor_blocks_${courseId}`);
    if (saved) {
      try {
        loadBlocks(JSON.parse(saved));
        blocksInitialized.current = true;
        return;
      } catch { /* ignore */ }
    }

    // Wait for course metadata to load before checking server-side layout
    if (!course) return;
    blocksInitialized.current = true;

    const savedLayout = (course.metadata as Record<string, unknown> | undefined)?.spaceLayout;
    if (savedLayout && typeof savedLayout === "object") {
      try {
        loadBlocks(savedLayout as Parameters<typeof loadBlocks>[0]);
        return;
      } catch { /* ignore */ }
    }

    const savedMode = (course.metadata as Record<string, unknown> | undefined)
      ?.learning_mode as LearningMode | undefined;
    if (savedMode) {
      loadBlocks(buildLayoutFromMode(savedMode));
    }
  }, [courseId, course, loadBlocks]);

  useEffect(() => {
    if (!blocksInitialized.current) return;
    clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      flushLayout();
    }, 2000);
    return () => clearTimeout(persistTimer.current);
  }, [blocks, flushLayout]);

  useEffect(() => {
    const flushNow = () => {
      clearTimeout(persistTimer.current);
      flushLayout();
    };

    window.addEventListener("pagehide", flushNow);
    window.addEventListener("beforeunload", flushNow);
    return () => {
      window.removeEventListener("pagehide", flushNow);
      window.removeEventListener("beforeunload", flushNow);
      flushNow();
    };
  }, [courseId, flushLayout]);

  return { blocks, blocksInitialized };
}
