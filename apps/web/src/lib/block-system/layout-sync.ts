import { updateCourseLayout } from "@/lib/api";
import type { SpaceLayout } from "./types";
import { updateUnlockContext } from "./feature-unlock";
import { saveStoredSpaceLayout } from "./layout-storage";

export function persistCourseSpaceLayoutLocally(courseId: string, layout: SpaceLayout): SpaceLayout {
  const persistedLayout = saveStoredSpaceLayout(courseId, layout);
  if (persistedLayout.mode) {
    updateUnlockContext(courseId, { mode: persistedLayout.mode });
  }
  return persistedLayout;
}

export async function syncCourseSpaceLayout(courseId: string, layout: SpaceLayout): Promise<SpaceLayout> {
  const persistedLayout = persistCourseSpaceLayoutLocally(courseId, layout);
  await updateCourseLayout(courseId, persistedLayout);
  return persistedLayout;
}
