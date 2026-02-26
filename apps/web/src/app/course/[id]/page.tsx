"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Upload, FileText, MessageSquare, BookOpen } from "lucide-react";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { Button } from "@/components/ui/button";
import { useCourseStore } from "@/store/course";
import { NotesPanel } from "@/components/course/notes-panel";
import { QuizPanel } from "@/components/course/quiz-panel";
import { ChatPanel } from "@/components/chat/chat-panel";
import { UploadDialog } from "@/components/course/upload-dialog";
import { useGroupRef } from "react-resizable-panels";

/**
 * Layout presets for three-panel system.
 * Reference: CopilotKit "Controlled Generative UI" pattern.
 * react-resizable-panels v4 imperative API: groupRef.current.setLayout({ panelId: size })
 */
const LAYOUT_PRESETS = {
  balanced: { notes: 33, quiz: 34, chat: 33 },
  notesFocused: { notes: 50, quiz: 25, chat: 25 },
  quizFocused: { notes: 20, quiz: 55, chat: 25 },
  chatFocused: { notes: 20, quiz: 20, chat: 60 },
  fullNotes: { notes: 80, quiz: 10, chat: 10 },
} as const;

type LayoutPreset = keyof typeof LAYOUT_PRESETS;

export default function CoursePage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params.id as string;
  const panelGroupRef = useGroupRef();

  const { activeCourse, setActiveCourse, courses, fetchCourses, contentTree } =
    useCourseStore();

  const [currentPreset, setCurrentPreset] = useState<LayoutPreset>("balanced");
  const [uploadOpen, setUploadOpen] = useState(false);

  useEffect(() => {
    if (courses.length === 0) {
      fetchCourses();
    }
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) {
      setActiveCourse(course);
    }
  }, [courseId, courses, setActiveCourse]);

  const applyPreset = (preset: LayoutPreset) => {
    setCurrentPreset(preset);
    panelGroupRef.current?.setLayout(LAYOUT_PRESETS[preset]);
  };

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Header */}
      <header className="border-b px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="font-semibold truncate">
            {activeCourse?.name || "Loading..."}
          </h1>
        </div>

        <div className="flex items-center gap-2">
          {/* Layout preset buttons */}
          <div className="flex gap-1 mr-2">
            {(Object.keys(LAYOUT_PRESETS) as LayoutPreset[]).map((preset) => (
              <Button
                key={preset}
                variant={currentPreset === preset ? "secondary" : "ghost"}
                size="sm"
                className="text-xs"
                onClick={() => applyPreset(preset)}
              >
                {preset === "balanced" && "Balanced"}
                {preset === "notesFocused" && "Notes"}
                {preset === "quizFocused" && "Quiz"}
                {preset === "chatFocused" && "Chat"}
                {preset === "fullNotes" && "Full"}
              </Button>
            ))}
          </div>

          <Button variant="outline" size="sm" onClick={() => setUploadOpen(true)}>
            <Upload className="h-4 w-4 mr-1" />
            Upload
          </Button>
        </div>
      </header>

      {/* Three-panel layout using react-resizable-panels (via shadcn Resizable) */}
      <ResizablePanelGroup
        groupRef={panelGroupRef}
        orientation="horizontal"
        className="flex-1"
      >
        {/* Panel 1: AI Notes */}
        <ResizablePanel id="notes" defaultSize={33} minSize={10}>
          <div className="h-full flex flex-col">
            <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0">
              <FileText className="h-4 w-4" />
              <span className="text-sm font-medium">Notes</span>
            </div>
            <NotesPanel contentTree={contentTree} />
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Panel 2: Quiz */}
        <ResizablePanel id="quiz" defaultSize={34} minSize={10}>
          <div className="h-full flex flex-col">
            <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0">
              <BookOpen className="h-4 w-4" />
              <span className="text-sm font-medium">Quiz</span>
            </div>
            <QuizPanel courseId={courseId} />
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        {/* Panel 3: AI Chat */}
        <ResizablePanel id="chat" defaultSize={33} minSize={10}>
          <div className="h-full flex flex-col">
            <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0">
              <MessageSquare className="h-4 w-4" />
              <span className="text-sm font-medium">AI Chat</span>
            </div>
            <ChatPanel courseId={courseId} />
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
      />
    </div>
  );
}
