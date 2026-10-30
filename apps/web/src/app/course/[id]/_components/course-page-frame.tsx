"use client";

import { useState, type ReactNode } from "react";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { useCourseContext } from "../_hooks/course-context";

interface CoursePageFrameProps {
  /** Fallback header title while the course has not loaded. */
  title: string;
  mainClassName?: string;
  children: ReactNode;
}

/**
 * Shared chrome for course sub-pages: workspace header, centred main column,
 * chat FAB + drawer. Pages only render their body.
 */
export function CoursePageFrame({ title, mainClassName, children }: CoursePageFrameProps) {
  const { courseId, course, aiActionsEnabled } = useCourseContext();
  const [chatOpen, setChatOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || title} courseId={courseId} />
      <main className={`flex-1 max-w-5xl mx-auto w-full px-4 py-6 ${mainClassName ?? ""}`}>
        {children}
      </main>
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
