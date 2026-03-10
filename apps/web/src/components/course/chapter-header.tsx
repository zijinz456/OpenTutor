"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

interface ChapterHeaderProps {
  courseId: string;
  courseName: string;
  chapterTitle: string;
}

export function ChapterHeader({ courseId, courseName, chapterTitle }: ChapterHeaderProps) {
  return (
    <header role="banner" aria-label="Chapter navigation" className="border-b border-border/60 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 sticky top-0 z-30">
      <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-3">
        <Link
          href={`/course/${courseId}`}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors shrink-0"
          aria-label={`Back to ${courseName}`}
        >
          <ArrowLeft className="size-4" />
          <span className="hidden sm:inline">{courseName}</span>
        </Link>
        <span className="text-muted-foreground/40" aria-hidden="true">/</span>
        <h1 className="text-sm font-medium text-foreground truncate">{chapterTitle}</h1>
      </div>
    </header>
  );
}
