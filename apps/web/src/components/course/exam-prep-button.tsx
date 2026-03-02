"use client";

import { GraduationCap } from "lucide-react";
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
      <span className={`inline-flex items-center gap-1 rounded-md bg-amber-100 text-amber-700 text-xs font-medium ${compact ? "px-1.5 py-0.5" : "px-2 py-1"}`}>
        <GraduationCap className="w-3.5 h-3.5" />
        {!compact && "Exam Prep"}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      disabled={isSwitching}
      className={`inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 text-amber-700 text-xs font-medium hover:bg-amber-100 transition-colors disabled:opacity-50 ${compact ? "px-1.5 py-0.5" : "px-2 py-1"}`}
    >
      <GraduationCap className="w-3.5 h-3.5" />
      {isSwitching ? "Switching..." : compact ? "Exam" : "Exam Prep"}
    </button>
  );
}
