"use client";

import { useCallback, useEffect, useRef } from "react";
import { syncCourseSpaceLayout } from "@/lib/block-system/layout-sync";
import { useWorkspaceStore } from "@/store/workspace";
import type { LearningMode } from "@/lib/block-system/types";
import { buildLayoutFromMode } from "@/lib/block-system/templates";
import {
  loadStoredSpaceLayout,
  parseSpaceLayout,
  saveStoredSpaceLayout,
} from "@/lib/block-system/layout-storage";

/**
 * Loads the workspace layout for a course and persists changes.
 *
 * The server (`course.metadata.spaceLayout`) is the source of truth.
 * localStorage is only a cold-start cache used while the course has not
 * loaded yet; once the course arrives the server layout wins and overwrites
 * the local cache.
 */
export function useBlockPersistence(
  courseId: string,
  course: { metadata?: unknown } | null,
) {
  const blocks = useWorkspaceStore((s) => s.spaceLayout.blocks);
  const loadBlocks = useWorkspaceStore((s) => s.loadBlocks);
  const blocksInitialized = useRef(false);
  const serverApplied = useRef(false);
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
      serverApplied.current = false;
    }
    if (serverApplied.current) return;

    const metadata = (course?.metadata as Record<string, unknown> | undefined) ?? undefined;

    // Server layout wins as soon as the course is loaded.
    if (course) {
      serverApplied.current = true;
      const serverLayout = parseSpaceLayout(metadata?.spaceLayout);
      if (serverLayout) {
        loadBlocks(serverLayout);
        saveStoredSpaceLayout(courseId, serverLayout);
        blocksInitialized.current = true;
        return;
      }

      // No server layout yet: keep whatever the cold-start cache gave us
      // (or load it now), otherwise fall back to the saved learning mode.
      if (blocksInitialized.current) return;
      const cached = loadStoredSpaceLayout(courseId);
      if (cached) {
        loadBlocks(cached);
      } else {
        const savedMode = metadata?.learning_mode as LearningMode | undefined;
        if (savedMode) loadBlocks(buildLayoutFromMode(savedMode));
      }
      blocksInitialized.current = true;
      return;
    }

    // Course not loaded yet: use the local cache so the first paint is not empty.
    if (blocksInitialized.current) return;
    const cached = loadStoredSpaceLayout(courseId);
    if (cached) {
      loadBlocks(cached);
      blocksInitialized.current = true;
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
