"use client";

interface StatusBarProps {
  courseName: string;
  chapterName?: string;
  practiceProgress?: string;
  studyTime?: string;
}

export function StatusBar({ courseName, chapterName, practiceProgress, studyTime }: StatusBarProps) {
  return (
    <div className="h-7 px-4 bg-[#1E1B4B] flex items-center gap-5 shrink-0">
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
    </div>
  );
}
