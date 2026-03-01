"use client";

interface StatusBarProps {
  courseName: string;
  chapterName?: string;
  practiceProgress?: string;
  studyTime?: string;
  activeGoalTitle?: string | null;
  activeTaskTitle?: string | null;
  sceneLabel?: string | null;
  nextActionTitle?: string | null;
}

export function StatusBar({
  courseName,
  chapterName,
  practiceProgress,
  studyTime,
  activeGoalTitle,
  activeTaskTitle,
  sceneLabel,
  nextActionTitle,
}: StatusBarProps) {
  return (
    <div className="min-h-7 px-4 py-1.5 bg-[#1E1B4B] flex flex-wrap items-center gap-x-5 gap-y-1 shrink-0">
      <span className="text-[11px] text-white/70 font-medium">{courseName}</span>
      {chapterName && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">{chapterName}</span>
        </>
      )}
      {practiceProgress && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">{practiceProgress}</span>
        </>
      )}
      {studyTime && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">Study time: {studyTime}</span>
        </>
      )}
      {activeGoalTitle && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">Goal: {activeGoalTitle}</span>
        </>
      )}
      {activeTaskTitle && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">Task: {activeTaskTitle}</span>
        </>
      )}
      {sceneLabel && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">Scene: {sceneLabel}</span>
        </>
      )}
      {nextActionTitle && (
        <>
          <div className="w-px h-3.5 bg-white/20" />
          <span className="text-[11px] text-white/50">Next: {nextActionTitle}</span>
        </>
      )}
    </div>
  );
}
