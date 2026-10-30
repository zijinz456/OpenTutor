import { updateCourseLayout } from "@/lib/api";
import type { SpaceLayout } from "./types";
import { saveStoredSpaceLayout } from "./layout-storage";

export function persistCourseSpaceLayoutLocally(courseId: string, layout: SpaceLayout): SpaceLayout {
  return saveStoredSpaceLayout(courseId, layout);
}

export async function syncCourseSpaceLayout(courseId: string, layout: SpaceLayout): Promise<SpaceLayout> {
  const persistedLayout = persistCourseSpaceLayoutLocally(courseId, layout);
  await updateCourseLayout(courseId, persistedLayout);
  return persistedLayout;
}
