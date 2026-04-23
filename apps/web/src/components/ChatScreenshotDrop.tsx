"use client";

/**
 * Chat-layout wrapper around <ScreenshotPrivacyBanner> + <ScreenshotDropZone>
 * (Phase 4 T5).
 *
 * The ScreenshotDropZone needs a concrete `courseId`. In OpenTutor the
 * "chat layout" is the per-course workspace (`/course/[id]` with the chat
 * drawer). We read `activeCourse` from the Zustand course store — populated
 * by `useCourseData` on mount — and bail early if nothing is active so we
 * never render a drop target that would POST with an empty course_id.
 *
 * When a save succeeds we surface a success toast via the shared `sonner`
 * notification util so the user gets reinforcement without needing to
 * scroll the dropzone into view.
 */

import { toast } from "sonner";
import { useCourseStore } from "@/store/course";
import { ScreenshotDropZone } from "./ScreenshotDropZone";
import { ScreenshotPrivacyBanner } from "./ScreenshotPrivacyBanner";
import type { ScreenshotSaveResult } from "@/lib/api/screenshot";

export function ChatScreenshotDrop() {
  const activeCourse = useCourseStore((s) => s.activeCourse);

  // No active course → don't render a dangling dropzone. Parent (course page)
  // mounts us inside a stack that already has other "needs course" widgets,
  // so a silent return is less noisy than a placeholder.
  if (!activeCourse) return null;

  const handleSaved = (result: ScreenshotSaveResult) => {
    toast.success(
      `Saved ${result.saved_count} card${result.saved_count === 1 ? "" : "s"} to FSRS queue`,
    );
  };

  return (
    <div
      className="flex flex-col gap-3"
      data-testid="chat-screenshot-drop"
    >
      <ScreenshotPrivacyBanner dismissible />
      <ScreenshotDropZone
        courseId={activeCourse.id}
        onSaved={handleSaved}
      />
    </div>
  );
}

export default ChatScreenshotDrop;
