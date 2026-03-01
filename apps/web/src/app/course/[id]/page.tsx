"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import {
  FileText,
  MessageSquare,
  BookOpen,
  Layers,
  BarChart3,
  Network,
  Upload,
  X,
  ClipboardCheck,
  CalendarDays,
} from "lucide-react";
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
import { ReviewPanel } from "@/components/course/review-panel";
import { StudyPlanPanel } from "@/components/course/study-plan-panel";
import { ActivityPanel } from "@/components/course/activity-panel";
import { NLTuningFAB } from "@/components/course/nl-tuning-fab";
import { ActivityBar } from "@/components/workspace/activity-bar";
import { StatusBar } from "@/components/workspace/status-bar";
import { useGroupRef } from "react-resizable-panels";
import { getFilesByCourseId, getFileUrl, getCourseProgress, type ChatAction, type SwitchResult } from "@/lib/api";
import { SceneSelector } from "@/components/scene/scene-selector";
import { PreferenceConfirmDialog } from "@/components/preference/preference-confirm-dialog";
import { useSceneStore } from "@/store/scene";
import { toast } from "sonner";
import { ErrorBoundary } from "@/components/error-boundary";

const PdfViewer = dynamic(
  () => import("@/components/course/pdf-viewer").then((mod) => mod.PdfViewer),
  { ssr: false },
);

const LAYOUT_PRESETS = {
  balanced: { pdf: 25, notes: 25, quiz: 25, chat: 25 },
  notesFocused: { pdf: 15, notes: 45, quiz: 20, chat: 20 },
  quizFocused: { pdf: 15, notes: 15, quiz: 50, chat: 20 },
  chatFocused: { pdf: 15, notes: 15, quiz: 15, chat: 55 },
  fullNotes: { pdf: 10, notes: 70, quiz: 10, chat: 10 },
} as const;

const RIGHT_TAB_TYPES = ["quiz", "flashcards", "progress", "graph", "review", "plan", "activity"] as const;
type LayoutPreset = keyof typeof LAYOUT_PRESETS;
type RightTab = (typeof RIGHT_TAB_TYPES)[number];
type HiddenPanelId = "pdf" | "notes" | "quiz" | "chat";

const RIGHT_TAB_META: Record<RightTab, { label: string; icon: ComponentType<{ className?: string }> }> = {
  quiz: { label: "Quiz", icon: BookOpen },
  flashcards: { label: "Cards", icon: Layers },
  progress: { label: "Stats", icon: BarChart3 },
  graph: { label: "Graph", icon: Network },
  review: { label: "Review", icon: ClipboardCheck },
  plan: { label: "Plan", icon: CalendarDays },
  activity: { label: "Activity", icon: Layers },
};

function isRightTab(value: string): value is RightTab {
  return RIGHT_TAB_TYPES.includes(value as RightTab);
}

function getActivityItemForRightTab(tab: RightTab): string {
  if (tab === "progress" || tab === "graph") return "progress";
  if (tab === "plan") return "chat";
  if (tab === "activity") return "activity";
  return "practice";
}

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;
  const panelGroupRef = useGroupRef();
  const initialSceneAppliedRef = useRef<string | null>(null);

  const { activeCourse, setActiveCourse, courses, fetchCourses, contentTree } =
    useCourseStore();
  const { setOnAction } = useChatStore();
  const { activeScene, sceneConfig, switchScene: doSwitchScene } = useSceneStore();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [rightTab, setRightTab] = useState<RightTab>("quiz");
  const [activityItem, setActivityItem] = useState("notes");
  const [hiddenPanels, setHiddenPanels] = useState<Set<HiddenPanelId>>(new Set());
  const [layoutPreset, setLayoutPreset] = useState<LayoutPreset>("balanced");
  const [pdfFileUrl, setPdfFileUrl] = useState<string | undefined>();
  const [pdfFileName, setPdfFileName] = useState<string | undefined>();
  const [studyTime, setStudyTime] = useState("0m");
  const [prefDialogOpen, setPrefDialogOpen] = useState(false);
  const [pendingPrefChanges, setPendingPrefChanges] = useState<Array<{ dimension: string; value: string }>>([]);

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

  useEffect(() => {
    getFilesByCourseId(courseId)
      .then((files) => {
        const pdf = files.find((f) => (f.filename || f.file_name || "").toLowerCase().endsWith(".pdf"));
        if (pdf) {
          setPdfFileUrl(getFileUrl(pdf.job_id || pdf.id));
          setPdfFileName(pdf.filename || pdf.file_name);
        }
      })
      .catch(() => { /* no files yet */ });

    getCourseProgress(courseId)
      .then((p) => {
        const mins = p.total_study_minutes;
        setStudyTime(mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins}m`);
      })
      .catch(() => { /* no progress yet */ });
  }, [courseId]);

  const applyPreset = useCallback((preset: LayoutPreset) => {
    panelGroupRef.current?.setLayout(LAYOUT_PRESETS[preset]);
    setLayoutPreset(preset);
  }, [panelGroupRef]);

  const buildWorkspaceState = useCallback(() => {
    const openTabs: Array<{ type: string; position: number }> = [];
    if (!hiddenPanels.has("pdf")) openTabs.push({ type: "pdf", position: openTabs.length });
    if (!hiddenPanels.has("notes")) openTabs.push({ type: "notes", position: openTabs.length });
    if (!hiddenPanels.has("quiz")) openTabs.push({ type: rightTab, position: openTabs.length });
    if (!hiddenPanels.has("chat")) openTabs.push({ type: "chat", position: openTabs.length });

    return {
      open_tabs: openTabs,
      layout_state: {
        hidden_panels: Array.from(hiddenPanels),
        right_tab: rightTab,
        activity_item: activityItem,
        layout_preset: layoutPreset,
      },
      last_active_tab: !hiddenPanels.has("quiz") ? rightTab : activityItem,
    };
  }, [activityItem, hiddenPanels, layoutPreset, rightTab]);

  const applyWorkspaceLayout = useCallback((tabLayout?: Array<{ type: string; position: number }>) => {
    if (!tabLayout?.length) return;

    const visibleTypes = new Set(tabLayout.map((item) => item.type));
    const nextHidden = new Set<HiddenPanelId>(["pdf", "notes", "quiz", "chat"]);

    if (visibleTypes.has("pdf")) nextHidden.delete("pdf");
    if (visibleTypes.has("notes")) nextHidden.delete("notes");
    if (visibleTypes.has("chat")) nextHidden.delete("chat");

    const firstRightTab = tabLayout
      .map((item) => item.type)
      .find((item): item is RightTab => isRightTab(item));

    if (firstRightTab) {
      nextHidden.delete("quiz");
      setRightTab(firstRightTab);
      setActivityItem(getActivityItemForRightTab(firstRightTab));
      applyPreset(firstRightTab === "plan" ? "notesFocused" : "quizFocused");
    } else if (visibleTypes.size >= 3) {
      applyPreset("balanced");
    }

    setHiddenPanels(nextHidden);
  }, [applyPreset]);

  const applySceneResult = useCallback((result: SwitchResult) => {
    if (result.tab_layout?.length) {
      applyWorkspaceLayout(result.tab_layout);
    } else if (result.config?.tab_preset?.length) {
      applyWorkspaceLayout(result.config.tab_preset);
    }

    for (const action of result.init_actions) {
      if (action.action === "load_wrong_answers") {
        setRightTab("review");
        setHiddenPanels((prev) => {
          const next = new Set(prev);
          next.delete("quiz");
          return next;
        });
      }
      if (action.action === "generate_study_plan") {
        setRightTab("plan");
        setHiddenPanels((prev) => {
          const next = new Set(prev);
          next.delete("quiz");
          return next;
        });
      }
      toast.message(action.message);
    }

    if (result.message) {
      toast.message(result.message);
    }
    if (result.explanation?.reason) {
      toast.message(result.explanation.reason);
    }
  }, [applyWorkspaceLayout]);

  const togglePanel = useCallback((panelId: HiddenPanelId) => {
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

  const handleSceneSwitch = useCallback(async (sceneId: string) => {
    const result = await doSwitchScene(courseId, sceneId, buildWorkspaceState());
    applySceneResult(result);
  }, [applySceneResult, buildWorkspaceState, courseId, doSwitchScene]);

  const handleAction = useCallback((action: ChatAction) => {
    if (action.action === "set_layout_preset" && action.value) {
      const preset = action.value as LayoutPreset;
      if (preset in LAYOUT_PRESETS) {
        applyPreset(preset);
      }
    } else if (action.action === "set_preference" && action.value && action.extra) {
      setPendingPrefChanges((prev) => [...prev, { dimension: action.value!, value: action.extra! }]);
      setPrefDialogOpen(true);
    } else if (action.action === "suggest_scene_switch" && action.value) {
      void handleSceneSwitch(action.value);
    }
  }, [applyPreset, handleSceneSwitch]);

  useEffect(() => {
    setOnAction(handleAction);
  }, [handleAction, setOnAction]);

  useEffect(() => {
    if (sceneConfig?.scene_id && initialSceneAppliedRef.current !== sceneConfig.scene_id) {
      initialSceneAppliedRef.current = sceneConfig.scene_id;
      queueMicrotask(() => applyWorkspaceLayout(sceneConfig.tab_preset));
    }
  }, [applyWorkspaceLayout, sceneConfig]);

  const handleActivityClick = useCallback((item: string) => {
    setActivityItem(item);
    if (item === "notes") {
      setHiddenPanels(new Set());
      setRightTab("quiz");
      applyPreset("notesFocused");
    } else if (item === "practice") {
      setRightTab("quiz");
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("quiz");
        return next;
      });
      applyPreset("quizFocused");
    } else if (item === "chat") {
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("chat");
        return next;
      });
      applyPreset("chatFocused");
    } else if (item === "progress") {
      setRightTab("progress");
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("quiz");
        return next;
      });
      applyPreset("quizFocused");
    } else if (item === "activity") {
      setRightTab("activity");
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("quiz");
        return next;
      });
      applyPreset("chatFocused");
    }
  }, [applyPreset]);

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

  const breadcrumbs = useMemo(() => [
    { label: activeCourse?.name || "Course", href: "/" },
    ...(contentTree.length > 0
      ? [{ label: contentTree[0]?.title || "Chapter" }]
      : []),
  ], [activeCourse?.name, contentTree]);

  return (
    <div className="h-screen flex flex-col bg-background">
      <div className="flex flex-1 overflow-hidden">
        <ActivityBar activeItem={activityItem} onItemClick={handleActivityClick} />

        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="h-9 px-4 bg-muted/50 border-b flex items-center gap-2 shrink-0">
            {breadcrumbs.map((item, idx) => (
              <span key={idx} className="flex items-center gap-2">
                {idx > 0 && <span className="text-muted-foreground text-xs">/</span>}
                {item.href ? (
                  <a href={item.href} className="text-xs font-medium text-primary hover:underline">{item.label}</a>
                ) : (
                  <span className="text-xs text-muted-foreground">{item.label}</span>
                )}
              </span>
            ))}
            <div className="ml-auto">
              <SceneSelector
                courseId={courseId}
                getCurrentUiState={buildWorkspaceState}
                onSwitch={(_sceneId, result) => applySceneResult(result)}
              />
            </div>
          </div>

          <div className="flex flex-1 overflow-hidden relative">
            <button
              onClick={() => setUploadOpen(true)}
              data-testid="workspace-upload-trigger"
              className="absolute top-3 right-3 z-20 h-9 px-3 rounded-md bg-background border border-border shadow-sm flex items-center gap-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
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
              {!hiddenPanels.has("pdf") && (
                <>
                  <ResizablePanel id="pdf" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
                        <FileText className="h-3.5 w-3.5 text-red-500" />
                        <span className="text-xs font-medium text-foreground flex-1 truncate">PDF Viewer</span>
                        <button onClick={() => togglePanel("pdf")} className="text-muted-foreground hover:text-foreground">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <ErrorBoundary><PdfViewer fileUrl={pdfFileUrl} fileName={pdfFileName} /></ErrorBoundary>
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {!hiddenPanels.has("notes") && (
                <>
                  <ResizablePanel id="notes" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
                        <FileText className="h-3.5 w-3.5 text-primary" />
                        <span className="text-xs font-medium text-foreground flex-1">Agent Notes</span>
                        <button onClick={() => togglePanel("notes")} className="text-muted-foreground hover:text-foreground">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <ErrorBoundary><NotesPanel courseId={courseId} contentTree={contentTree} /></ErrorBoundary>
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {!hiddenPanels.has("quiz") && (
                <>
                  <ResizablePanel id="quiz" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-1 py-1 flex items-center gap-0.5 shrink-0 bg-muted/50 overflow-x-auto">
                        {(Object.entries(RIGHT_TAB_META) as Array<[RightTab, typeof RIGHT_TAB_META[RightTab]]>).map(([tab, meta]) => {
                          const Icon = meta.icon;
                          return (
                            <Button
                              key={tab}
                              variant={rightTab === tab ? "secondary" : "ghost"}
                              size="sm"
                              className="text-xs h-7 px-2"
                              onClick={() => setRightTab(tab)}
                            >
                              <Icon className="h-3 w-3 mr-1" />
                              {meta.label}
                            </Button>
                          );
                        })}
                        <div className="flex-1 min-w-2" />
                        <button onClick={() => togglePanel("quiz")} className="text-muted-foreground hover:text-foreground px-1">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <ErrorBoundary>
                        {rightTab === "quiz" && <QuizPanel courseId={courseId} />}
                        {rightTab === "flashcards" && <FlashcardPanel courseId={courseId} />}
                        {rightTab === "progress" && <ProgressPanel courseId={courseId} />}
                        {rightTab === "graph" && <KnowledgeGraph courseId={courseId} />}
                        {rightTab === "review" && <ReviewPanel courseId={courseId} />}
                        {rightTab === "plan" && <StudyPlanPanel courseId={courseId} />}
                        {rightTab === "activity" && <ActivityPanel courseId={courseId} />}
                      </ErrorBoundary>
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {!hiddenPanels.has("chat") && (
                <ResizablePanel id="chat" defaultSize={25} minSize={8}>
                  <div className="h-full flex flex-col">
                    <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
                      <MessageSquare className="h-3.5 w-3.5 text-primary" />
                      <span className="text-xs font-medium text-foreground flex-1">Q&A</span>
                      <button onClick={() => togglePanel("chat")} className="text-muted-foreground hover:text-foreground">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <ErrorBoundary><ChatPanel courseId={courseId} activeTab={activityItem} scene={activeScene} /></ErrorBoundary>
                  </div>
                </ResizablePanel>
              )}
            </ResizablePanelGroup>

            <NLTuningFAB courseId={courseId} />
          </div>

          {hiddenPanels.size > 0 && (
            <div className="h-8 px-3 bg-muted/50 border-t flex items-center gap-2 shrink-0">
              <span className="text-[11px] text-muted-foreground">Hidden:</span>
              {Array.from(hiddenPanels).map((panelId) => (
                <button
                  key={panelId}
                  onClick={() => togglePanel(panelId)}
                  className="px-2 py-0.5 bg-background border border-border rounded text-[11px] text-muted-foreground hover:border-primary hover:text-primary"
                >
                  {panelId === "pdf"
                    ? "PDF"
                    : panelId === "notes"
                      ? "Notes"
                      : panelId === "quiz"
                        ? RIGHT_TAB_META[rightTab].label
                        : "Chat"} +
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <StatusBar
        courseName={activeCourse?.name || "Loading..."}
        chapterName={contentTree.length > 0 ? contentTree[0]?.title : undefined}
        studyTime={studyTime}
      />

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courseId={courseId}
      />

      <PreferenceConfirmDialog
        open={prefDialogOpen}
        onOpenChange={(open) => {
          setPrefDialogOpen(open);
          if (!open) setPendingPrefChanges([]);
        }}
        changes={pendingPrefChanges}
        courseId={courseId}
      />
    </div>
  );
}
