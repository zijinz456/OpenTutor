"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { FileText, MessageSquare, BookOpen, Layers, BarChart3, Network, Upload, X } from "lucide-react";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { Button } from "@/components/ui/button";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { NotesPanel } from "@/components/course/notes-panel";
import { QuizPanel } from "@/components/course/quiz-panel";
import { ChatPanel } from "@/components/chat/chat-panel";
import { UploadDialog } from "@/components/course/upload-dialog";
import { FlashcardPanel } from "@/components/course/flashcard-panel";
import { ProgressPanel } from "@/components/course/progress-panel";
import { KnowledgeGraph } from "@/components/course/knowledge-graph";
import { PdfViewer } from "@/components/course/pdf-viewer";
import { NLTuningFAB } from "@/components/course/nl-tuning-fab";
import { ActivityBar } from "@/components/workspace/activity-bar";
import { StatusBar } from "@/components/workspace/status-bar";
import { useGroupRef } from "react-resizable-panels";
import { setPreference, type ChatAction } from "@/lib/api";
import { SceneSelector } from "@/components/scene/scene-selector";
import { useSceneStore } from "@/store/scene";

const LAYOUT_PRESETS = {
  balanced: { pdf: 25, notes: 25, quiz: 25, chat: 25 },
  notesFocused: { pdf: 15, notes: 45, quiz: 20, chat: 20 },
  quizFocused: { pdf: 15, notes: 15, quiz: 50, chat: 20 },
  chatFocused: { pdf: 15, notes: 15, quiz: 15, chat: 55 },
  fullNotes: { pdf: 10, notes: 70, quiz: 10, chat: 10 },
} as const;

type LayoutPreset = keyof typeof LAYOUT_PRESETS;

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;
  const panelGroupRef = useGroupRef();

  const { activeCourse, setActiveCourse, courses, fetchCourses, contentTree } =
    useCourseStore();
  const { setOnAction } = useChatStore();
  const { activeScene, switchScene: doSwitchScene } = useSceneStore();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [rightTab, setRightTab] = useState<"quiz" | "flashcards" | "progress" | "graph">("quiz");
  const [activityItem, setActivityItem] = useState("notes");
  const [hiddenPanels, setHiddenPanels] = useState<Set<string>>(new Set());

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

  const applyPreset = useCallback((preset: LayoutPreset) => {
    panelGroupRef.current?.setLayout(LAYOUT_PRESETS[preset]);
  }, [panelGroupRef]);

  const togglePanel = useCallback((panelId: string) => {
    setHiddenPanels((prev) => {
      const next = new Set(prev);
      if (next.has(panelId)) {
        next.delete(panelId);
      } else {
        next.add(panelId);
      }
      return next;
    });
  }, []);

  const handleAction = useCallback((action: ChatAction) => {
    if (action.action === "set_layout_preset" && action.value) {
      const preset = action.value as LayoutPreset;
      if (preset in LAYOUT_PRESETS) {
        applyPreset(preset);
      }
    } else if (action.action === "set_preference" && action.value && action.extra) {
      setPreference(action.value, action.extra, "course", courseId, "nl_tuning");
    } else if (action.action === "suggest_scene_switch" && action.value) {
      // AI suggested a scene switch — execute it
      doSwitchScene(courseId, action.value);
    }
  }, [applyPreset, courseId, doSwitchScene]);

  useEffect(() => {
    setOnAction(handleAction);
  }, [handleAction, setOnAction]);

  // Activity bar navigation
  const handleActivityClick = useCallback((item: string) => {
    setActivityItem(item);
    if (item === "notes") {
      setHiddenPanels(new Set());
      applyPreset("notesFocused");
    } else if (item === "practice") {
      setRightTab("quiz");
      applyPreset("quizFocused");
    } else if (item === "chat") {
      applyPreset("chatFocused");
    } else if (item === "progress") {
      setRightTab("progress");
      applyPreset("quizFocused");
    }
  }, [applyPreset]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      switch (e.key) {
        case "1": e.preventDefault(); applyPreset("notesFocused"); break;
        case "2": e.preventDefault(); applyPreset("quizFocused"); break;
        case "3": e.preventDefault(); applyPreset("chatFocused"); break;
        case "0": e.preventDefault(); applyPreset("balanced"); break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [applyPreset]);

  // Build breadcrumb items from content tree
  const breadcrumbs = [
    { label: activeCourse?.name || "Course", href: "/" },
    ...(contentTree.length > 0
      ? [{ label: contentTree[0]?.title || "Chapter" }]
      : []),
  ];

  return (
    <div className="h-screen flex flex-col bg-white">
      <div className="flex flex-1 overflow-hidden">
        {/* Activity Bar */}
        <ActivityBar activeItem={activityItem} onItemClick={handleActivityClick} />

        {/* Main Content */}
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Breadcrumbs + Scene Selector */}
          <div className="h-9 px-4 bg-gray-50 border-b flex items-center gap-2 shrink-0">
            {breadcrumbs.map((item, idx) => (
              <span key={idx} className="flex items-center gap-2">
                {idx > 0 && <span className="text-gray-400 text-xs">/</span>}
                {item.href ? (
                  <a href={item.href} className="text-xs font-medium text-indigo-600 hover:underline">{item.label}</a>
                ) : (
                  <span className="text-xs text-gray-500">{item.label}</span>
                )}
              </span>
            ))}
            <div className="ml-auto">
              <SceneSelector courseId={courseId} />
            </div>
          </div>

          {/* Panels Area */}
          <div className="flex flex-1 overflow-hidden relative">
            <button
              onClick={() => setUploadOpen(true)}
              className="absolute top-3 right-3 z-20 h-9 px-3 rounded-md bg-white border border-gray-200 shadow-sm flex items-center gap-1.5 text-xs font-medium text-gray-700 hover:border-indigo-600 hover:text-indigo-600"
              title="Upload materials"
            >
              <Upload className="w-3.5 h-3.5" />
              Upload
            </button>

            <ResizablePanelGroup
              groupRef={panelGroupRef}
              orientation="horizontal"
              className="flex-1"
            >
              {/* Panel 1: PDF Viewer */}
              {!hiddenPanels.has("pdf") && (
                <>
                  <ResizablePanel id="pdf" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-gray-50">
                        <FileText className="h-3.5 w-3.5 text-red-500" />
                        <span className="text-xs font-medium text-gray-900 flex-1 truncate">PDF Viewer</span>
                        <button onClick={() => togglePanel("pdf")} className="text-gray-400 hover:text-gray-700">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <PdfViewer />
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {/* Panel 2: AI Notes */}
              {!hiddenPanels.has("notes") && (
                <>
                  <ResizablePanel id="notes" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-gray-50">
                        <FileText className="h-3.5 w-3.5 text-indigo-600" />
                        <span className="text-xs font-medium text-gray-900 flex-1">Agent Notes</span>
                        <button onClick={() => togglePanel("notes")} className="text-gray-400 hover:text-gray-700">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <NotesPanel contentTree={contentTree} />
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {/* Panel 3: Quiz / Flashcards / Progress / Graph (tabbed) */}
              {!hiddenPanels.has("quiz") && (
                <>
                  <ResizablePanel id="quiz" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-1 py-1 flex items-center gap-0.5 shrink-0 bg-gray-50">
                        <Button
                          variant={rightTab === "quiz" ? "secondary" : "ghost"}
                          size="sm"
                          className="text-xs h-7 px-2"
                          onClick={() => setRightTab("quiz")}
                        >
                          <BookOpen className="h-3 w-3 mr-1" />
                          Quiz
                        </Button>
                        <Button
                          variant={rightTab === "flashcards" ? "secondary" : "ghost"}
                          size="sm"
                          className="text-xs h-7 px-2"
                          onClick={() => setRightTab("flashcards")}
                        >
                          <Layers className="h-3 w-3 mr-1" />
                          Cards
                        </Button>
                        <Button
                          variant={rightTab === "progress" ? "secondary" : "ghost"}
                          size="sm"
                          className="text-xs h-7 px-2"
                          onClick={() => setRightTab("progress")}
                        >
                          <BarChart3 className="h-3 w-3 mr-1" />
                          Stats
                        </Button>
                        <Button
                          variant={rightTab === "graph" ? "secondary" : "ghost"}
                          size="sm"
                          className="text-xs h-7 px-2"
                          onClick={() => setRightTab("graph")}
                        >
                          <Network className="h-3 w-3 mr-1" />
                          Graph
                        </Button>
                        <div className="flex-1" />
                        <button onClick={() => togglePanel("quiz")} className="text-gray-400 hover:text-gray-700 px-1">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      {rightTab === "quiz" && <QuizPanel courseId={courseId} />}
                      {rightTab === "flashcards" && <FlashcardPanel courseId={courseId} />}
                      {rightTab === "progress" && <ProgressPanel courseId={courseId} />}
                      {rightTab === "graph" && <KnowledgeGraph courseId={courseId} />}
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {/* Panel 4: Chat */}
              {!hiddenPanels.has("chat") && (
                <ResizablePanel id="chat" defaultSize={25} minSize={8}>
                  <div className="h-full flex flex-col">
                    <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-gray-50">
                      <MessageSquare className="h-3.5 w-3.5 text-indigo-600" />
                      <span className="text-xs font-medium text-gray-900 flex-1">Q&A</span>
                      <button onClick={() => togglePanel("chat")} className="text-gray-400 hover:text-gray-700">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <ChatPanel courseId={courseId} activeTab={activityItem} scene={activeScene} />
                  </div>
                </ResizablePanel>
              )}
            </ResizablePanelGroup>

            {/* NL Tuning FAB */}
            <NLTuningFAB courseId={courseId} />
          </div>

          {/* Restore hidden panels bar */}
          {hiddenPanels.size > 0 && (
            <div className="h-8 px-3 bg-gray-50 border-t flex items-center gap-2 shrink-0">
              <span className="text-[11px] text-gray-400">Hidden:</span>
              {Array.from(hiddenPanels).map((p) => (
                <button
                  key={p}
                  onClick={() => togglePanel(p)}
                  className="px-2 py-0.5 bg-white border border-gray-200 rounded text-[11px] text-gray-600 hover:border-indigo-600 hover:text-indigo-600"
                >
                  {p === "pdf" ? "PDF" : p === "notes" ? "Notes" : p === "quiz" ? "Quiz/Cards" : "Chat"} +
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Status Bar */}
      <StatusBar
        courseName={activeCourse?.name || "Loading..."}
        chapterName={contentTree.length > 0 ? contentTree[0]?.title : undefined}
        studyTime="0m"
      />

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
      />
    </div>
  );
}
