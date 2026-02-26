"use client";

import { ScrollArea } from "@/components/ui/scroll-area";

/**
 * Quiz Panel — interactive question answering.
 *
 * Phase 0-A: Empty placeholder.
 * Phase 0-B: Full quiz extraction + interactive UI.
 * Reference: Quenti (quenti-io/quenti) React quiz components.
 * Reference: Obsidian Quiz Generator for 7 question type prompts.
 */

interface QuizPanelProps {
  courseId: string;
}

export function QuizPanel({ courseId }: QuizPanelProps) {
  return (
    <ScrollArea className="flex-1 p-4">
      <div className="flex items-center justify-center h-full min-h-[200px]">
        <div className="text-center">
          <p className="text-muted-foreground text-sm">Quiz panel</p>
          <p className="text-muted-foreground text-xs mt-1">
            Practice problems will appear here after content is uploaded
          </p>
          <p className="text-muted-foreground text-xs mt-1">
            (Phase 0-B: AI question extraction + interactive answering)
          </p>
        </div>
      </div>
    </ScrollArea>
  );
}
