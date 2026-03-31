"use client";

import { useCallback, useEffect, useRef } from "react";
import { syncCourseSpaceLayout } from "@/lib/block-system/layout-sync";
import { useWorkspaceStore } from "@/store/workspace";
import type { LearningMode } from "@/lib/block-system/types";
import { buildLayoutFromMode } from "@/lib/block-system/templates";
import { loadStoredSpaceLayout, parseSpaceLayout } from "@/lib/block-system/layout-storage";

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
    syncCourseSpaceLayout(courseId, layout).catch((e) => console.error("[Course] layout persist failed:", e));
  }, [courseId]);

  useEffect(() => {
    if (lastCourseIdRef.current !== courseId) {
      lastCourseIdRef.current = courseId;
      blocksInitialized.current = false;
    }
    if (blocksInitialized.current) return;

    // Try localStorage first (always available)
    const saved = loadStoredSpaceLayout(courseId);
    if (saved) {
      loadBlocks(saved);
      blocksInitialized.current = true;
      return;
    }

    // Wait for course metadata to load before checking server-side layout
    if (!course) return;
    blocksInitialized.current = true;

    const savedLayout = parseSpaceLayout(
      (course.metadata as Record<string, unknown> | undefined)?.spaceLayout,
    );
    if (savedLayout) {
      loadBlocks(savedLayout);
      return;
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
