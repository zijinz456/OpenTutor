"use client";

import { useSceneStore } from "@/store/scene";

interface ExamPrepButtonProps {
  courseId: string;
  onActivated?: () => void;
  compact?: boolean;
}

export function ExamPrepButton({ courseId, onActivated, compact }: ExamPrepButtonProps) {
  const { activeScene, switchScene, isSwitching } = useSceneStore();
  const isActive = activeScene === "exam_prep";

  const handleClick = async () => {
    if (isActive || isSwitching) return;
    await switchScene(courseId, "exam_prep");
    onActivated?.();
  };

  if (isActive) {
    return (
      <span className={`inline-flex items-center gap-1 rounded-md bg-warning-muted text-warning text-xs font-medium ${compact ? "px-1.5 py-0.5" : "px-2 py-1"}`}>
        {!compact && "Exam Prep"}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      disabled={isSwitching}
      className={`inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning-muted text-warning text-xs font-medium hover:bg-warning-muted/80 transition-colors disabled:opacity-50 ${compact ? "px-1.5 py-0.5" : "px-2 py-1"}`}
    >
      {isSwitching ? "Switching..." : compact ? "Exam" : "Exam Prep"}
    </button>
  );
}
