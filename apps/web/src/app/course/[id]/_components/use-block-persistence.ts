"use client";

import { useEffect, useRef } from "react";
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

  useEffect(() => {
    if (lastCourseIdRef.current !== courseId) {
      lastCourseIdRef.current = courseId;
      blocksInitialized.current = false;
    }
    if (blocksInitialized.current) return;
    blocksInitialized.current = true;

    const saved = localStorage.getItem(`opentutor_blocks_${courseId}`);
    if (saved) {
      try {
        loadBlocks(JSON.parse(saved));
        return;
      } catch { /* ignore */ }
    }

    const savedLayout = (course?.metadata as Record<string, unknown> | undefined)?.spaceLayout;
    if (savedLayout && typeof savedLayout === "object") {
      try {
        loadBlocks(savedLayout as Parameters<typeof loadBlocks>[0]);
        return;
      } catch { /* ignore */ }
    }

    const savedMode = (course?.metadata as Record<string, unknown> | undefined)
      ?.learning_mode as LearningMode | undefined;
    if (savedMode) {
      loadBlocks(buildLayoutFromMode(savedMode));
    }
  }, [courseId, course, loadBlocks]);

  useEffect(() => {
    if (!blocksInitialized.current || blocks.length === 0) return;
    clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      const layout = useWorkspaceStore.getState().spaceLayout;
      localStorage.setItem(`opentutor_blocks_${courseId}`, JSON.stringify(layout));
      updateCourseLayout(courseId, layout as unknown as Record<string, unknown>).catch((e) => console.error("[Course] layout persist failed:", e));
    }, 2000);
    return () => clearTimeout(persistTimer.current);
  }, [blocks, courseId]);

  return { blocks, blocksInitialized };
}
