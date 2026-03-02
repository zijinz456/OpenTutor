"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  FileText,
  MessageSquare,
  BookOpen,
  Layers,
  Upload,
  X,
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
import { AgentFocusStrip } from "@/components/course/agent-focus-strip";
import { NLTuningFAB } from "@/components/course/nl-tuning-fab";
import { AutoGenBanner } from "@/components/course/auto-gen-banner";
import { ActivityBar } from "@/components/workspace/activity-bar";
import { StatusBar } from "@/components/workspace/status-bar";
import { getFilesByCourseId, getFileUrl, getCourseProgress, queueNextAction as queueNextActionRequest } from "@/lib/api";
import { SceneSelector } from "@/components/scene/scene-selector";
import { PreferenceConfirmDialog } from "@/components/preference/preference-confirm-dialog";
import { useSceneStore } from "@/store/scene";
import { toast } from "sonner";
import { ErrorBoundary } from "@/components/error-boundary";
import { useActivityPolling } from "@/hooks/use-activity-polling";
import { useIsMobile } from "@/hooks/use-mobile";
import { NotificationPrompt } from "@/components/notification-prompt";
import { ExamPrepButton } from "@/components/course/exam-prep-button";
import {
  getDefaultMobileTab,
  isRightTabEnabled,
  resolveWorkspaceFeatures,
} from "@/lib/course-config";
import { RIGHT_TAB_META, type RightTab } from "./workspace-types";
import { useWorkspaceLayout } from "./use-workspace-layout";

/* ---- Dynamic imports ---- */

const PdfViewer = dynamic(
  () => import("@/components/course/pdf-viewer").then((mod) => mod.PdfViewer),
  { ssr: false },
);

function TabLoadingPlaceholder() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="animate-pulse flex flex-col items-center gap-3">
        <div className="w-8 h-8 bg-muted rounded-lg" />
        <div className="h-3 bg-muted rounded w-24" />
      </div>
    </div>
  );
}

/* Dynamically import heavy tab components that are behind tabs (not visible on initial render).
   The default visible tab is "quiz" (QuizPanel), so it stays statically imported. */
const FlashcardPanel = dynamic(
  () => import("@/components/course/flashcard-panel").then((mod) => mod.FlashcardPanel),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);
const ProgressPanel = dynamic(
  () => import("@/components/course/progress-panel").then((mod) => mod.ProgressPanel),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);
const KnowledgeGraph = dynamic(
  () => import("@/components/course/knowledge-graph").then((mod) => mod.KnowledgeGraph),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);
const ReviewPanel = dynamic(
  () => import("@/components/course/review-panel").then((mod) => mod.ReviewPanel),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);
const StudyPlanPanel = dynamic(
  () => import("@/components/course/study-plan-panel").then((mod) => mod.StudyPlanPanel),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);
const ActivityPanel = dynamic(
  () => import("@/components/course/activity-panel").then((mod) => mod.ActivityPanel),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);
const LearningProfilePanel = dynamic(
  () => import("@/components/course/learning-profile-panel").then((mod) => mod.LearningProfilePanel),
  { ssr: false, loading: () => <TabLoadingPlaceholder /> },
);

/* ---- Helpers ---- */

function getPracticeLandingTab(features: ReturnType<typeof resolveWorkspaceFeatures>): RightTab {
  if (features.practice) return "quiz";
  if (features.wrong_answer) return "review";
  if (features.study_plan) return "plan";
  return "progress";
}

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;
  const isMobile = useIsMobile();

  const { activeCourse, setActiveCourse, courses, fetchCourses, contentTree } = useCourseStore();
  const { activeScene, scenes } = useSceneStore();
  const { tasks, goals, nextAction, refresh } = useActivityPolling(courseId, 5000);

  const workspaceFeatures = useMemo(
    () => resolveWorkspaceFeatures(activeCourse?.metadata),
    [activeCourse?.metadata],
  );
  const availableRightTabs = useMemo(
    () =>
      (Object.keys(RIGHT_TAB_META) as RightTab[]).filter((tab) =>
        isRightTabEnabled(tab, workspaceFeatures),
      ),
    [workspaceFeatures],
  );
  const practiceLandingTab = useMemo(
    () => getPracticeLandingTab(workspaceFeatures),
    [workspaceFeatures],
  );
  const availableActivityItems = useMemo(
    () =>
      [
        workspaceFeatures.notes ? { id: "notes", title: "Notes" } : null,
        (workspaceFeatures.practice || workspaceFeatures.wrong_answer || workspaceFeatures.study_plan)
          ? { id: "practice", title: "Practice" }
          : null,
        workspaceFeatures.free_qa ? { id: "chat", title: "Chat" } : null,
        { id: "progress", title: "Progress" },
        { id: "activity", title: "Activity" },
        { id: "profile", title: "Profile" },
      ].filter((item): item is { id: string; title: string } => Boolean(item)),
    [workspaceFeatures],
  );
  const layout = useWorkspaceLayout(courseId, workspaceFeatures);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<"chat" | "notes" | "practice" | "pdf">("chat");
  const [pdfFileUrl, setPdfFileUrl] = useState<string | undefined>();
  const [pdfFileName, setPdfFileName] = useState<string | undefined>();
  const [studyTime, setStudyTime] = useState("0m");
  const [queueingNextAction, setQueueingNextAction] = useState(false);

  useEffect(() => {
    if (courses.length === 0) fetchCourses();
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((candidate) => candidate.id === courseId);
    if (course) setActiveCourse(course);
  }, [courseId, courses, setActiveCourse]);

  useEffect(() => {
    const promptKey = `course_init_prompt_${courseId}`;
    const consumedKey = `course_init_prompt_consumed_${courseId}`;
    const initPrompt = localStorage.getItem(promptKey);
    const alreadyConsumed = sessionStorage.getItem(consumedKey) === "true";
    if (initPrompt && !alreadyConsumed) {
      sessionStorage.setItem(consumedKey, "true");
      const timer = setTimeout(() => {
        void useChatStore.getState().sendMessage(courseId, initPrompt);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [courseId]);

  useEffect(() => {
    getFilesByCourseId(courseId)
      .then((files) => {
        const pdf = files.find((file) =>
          (file.filename || file.file_name || "").toLowerCase().endsWith(".pdf"),
        );
        if (pdf) {
          setPdfFileUrl(getFileUrl(pdf.job_id || pdf.id));
          setPdfFileName(pdf.filename || pdf.file_name);
        }
      })
      .catch(() => {});

    getCourseProgress(courseId)
      .then((progress) => {
        const minutes = progress.total_study_minutes;
        setStudyTime(minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`);
      })
      .catch(() => {});
  }, [courseId]);

  useEffect(() => {
    if (!availableRightTabs.includes(layout.rightTab)) {
      layout.setRightTab(availableRightTabs[0] ?? "progress");
    }
  }, [availableRightTabs, layout]);

  useEffect(() => {
    const nextDefaultTab = getDefaultMobileTab(workspaceFeatures);
    if (
      (mobileTab === "chat" && !workspaceFeatures.free_qa) ||
      (mobileTab === "notes" && !workspaceFeatures.notes) ||
      (mobileTab === "practice" && availableRightTabs.length === 0)
    ) {
      setMobileTab(nextDefaultTab);
    }
  }, [availableRightTabs.length, mobileTab, workspaceFeatures]);

  const activeGoal = useMemo(
    () => goals.find((goal) => goal.status === "active") ?? null,
    [goals],
  );
  const activeTask = useMemo(
    () =>
      tasks.find((task) =>
        ["pending_approval", "queued", "running", "resuming", "cancel_requested"].includes(task.status),
      ) ?? null,
    [tasks],
  );
  const sceneLabel = useMemo(() => {
    const matched = scenes.find((scene) => scene.scene_id === activeScene);
    return matched?.display_name || activeScene;
  }, [activeScene, scenes]);

  useEffect(() => {
    layout.setActiveTaskTracked(activeTask);
  }, [activeTask, layout]);

  const openActivityCockpit = useCallback(() => {
    layout.handleActivityClick("activity");
  }, [layout]);

  const openPractice = useCallback((tab: RightTab) => {
    layout.handleActivityClick("practice");
    layout.setRightTab(tab);
    if (isMobile) {
      setMobileTab("practice");
    }
  }, [isMobile, layout]);

  const queueRecommendedTask = useCallback(async () => {
    if (!nextAction) return;
    setQueueingNextAction(true);
    try {
      const task = await queueNextActionRequest(courseId);
      toast.success(`Queued ${task.title}`);
      openActivityCockpit();
      await refresh();
    } catch (error) {
      toast.error((error as Error).message || "Failed to queue next action");
    } finally {
      setQueueingNextAction(false);
    }
  }, [courseId, nextAction, openActivityCockpit, refresh]);

  const breadcrumbs = useMemo(
    () => [
      { label: activeCourse?.name || "Course", href: "/" },
      ...(contentTree.length > 0 ? [{ label: contentTree[0]?.title || "Chapter" }] : []),
    ],
    [activeCourse?.name, contentTree],
  );

  const mobileTabs = useMemo(
    () =>
      [
        workspaceFeatures.free_qa ? { id: "chat" as const, icon: MessageSquare, label: "Chat" } : null,
        workspaceFeatures.notes ? { id: "notes" as const, icon: FileText, label: "Notes" } : null,
        availableRightTabs.length > 0 ? { id: "practice" as const, icon: BookOpen, label: "Practice" } : null,
        { id: "pdf" as const, icon: Layers, label: "PDF" },
      ].filter(
        (
          tab,
        ): tab is {
          id: "chat" | "notes" | "practice" | "pdf";
          icon: typeof MessageSquare;
          label: string;
        } => Boolean(tab),
      ),
    [availableRightTabs.length, workspaceFeatures.free_qa, workspaceFeatures.notes],
  );

  const hiddenPanels = useMemo(
    () =>
      Array.from(layout.hiddenPanels).filter((panelId) => {
        if (panelId === "notes") return workspaceFeatures.notes;
        if (panelId === "chat") return workspaceFeatures.free_qa;
        return true;
      }),
    [layout.hiddenPanels, workspaceFeatures.free_qa, workspaceFeatures.notes],
  );

  const dialogs = (
    <>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} courseId={courseId} />
      <PreferenceConfirmDialog
        open={layout.prefDialogOpen}
        onOpenChange={(open) => {
          layout.setPrefDialogOpen(open);
          if (!open) layout.setPendingPrefChanges([]);
        }}
        changes={layout.pendingPrefChanges}
        courseId={courseId}
      />
    </>
  );

  const rightTabContent = (
    <ErrorBoundary>
      {layout.rightTab === "quiz" && <QuizPanel courseId={courseId} />}
      {layout.rightTab === "flashcards" && <FlashcardPanel courseId={courseId} />}
      {layout.rightTab === "progress" && <ProgressPanel courseId={courseId} />}
      {layout.rightTab === "graph" && <KnowledgeGraph courseId={courseId} />}
      {layout.rightTab === "review" && <ReviewPanel courseId={courseId} />}
      {layout.rightTab === "plan" && <StudyPlanPanel courseId={courseId} />}
      {layout.rightTab === "activity" && <ActivityPanel courseId={courseId} />}
      {layout.rightTab === "profile" && <LearningProfilePanel courseId={courseId} />}
    </ErrorBoundary>
  );

  const rightTabBar = (
    <div className="border-b px-1 py-1 flex items-center gap-0.5 shrink-0 bg-muted/50 overflow-x-auto">
      {availableRightTabs.map((tab) => {
        const meta = RIGHT_TAB_META[tab];
        const Icon = meta.icon;
        return (
          <Button
            key={tab}
            variant={layout.rightTab === tab ? "secondary" : "ghost"}
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => {
              layout.setRightTab(tab);
            }}
          >
            <Icon className="h-3 w-3 mr-1" />
            {meta.label}
          </Button>
        );
      })}
    </div>
  );

  if (isMobile) {
    return (
      <div className="h-screen flex flex-col bg-background">
        <div className="h-11 px-3 bg-muted/50 border-b flex items-center gap-2 shrink-0">
          <Link href="/" className="text-xs font-medium text-primary truncate max-w-[40%]">
            {activeCourse?.name || "Course"}
          </Link>
          <div className="ml-auto flex items-center gap-2">
            {workspaceFeatures.study_plan && (
              <ExamPrepButton
                courseId={courseId}
                compact
                onActivated={() => openPractice(workspaceFeatures.study_plan ? "plan" : practiceLandingTab)}
              />
            )}
            <SceneSelector
              courseId={courseId}
              activeTab={mobileTab === "practice" ? layout.rightTab : mobileTab}
              getCurrentUiState={layout.buildWorkspaceState}
              onSwitch={(_id, result) => layout.applySceneResult(result)}
            />
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="h-7 px-2 rounded-md bg-background border border-border text-xs font-medium"
              title="Upload"
            >
              <Upload className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {workspaceFeatures.practice && (
          <AutoGenBanner courseId={courseId} onQuizReady={() => openPractice("quiz")} />
        )}
        <NotificationPrompt />

        <div className="flex-1 overflow-hidden">
          {workspaceFeatures.free_qa && mobileTab === "chat" && (
            <ErrorBoundary>
              <ChatPanel courseId={courseId} activeTab={layout.activityItem} scene={activeScene} />
            </ErrorBoundary>
          )}
          {workspaceFeatures.notes && mobileTab === "notes" && (
            <ErrorBoundary>
              <NotesPanel courseId={courseId} contentTree={contentTree} />
            </ErrorBoundary>
          )}
          {mobileTab === "practice" && availableRightTabs.length > 0 && (
            <div className="h-full flex flex-col">
              {rightTabBar}
              {rightTabContent}
            </div>
          )}
          {mobileTab === "pdf" && (
            <ErrorBoundary>
              <PdfViewer fileUrl={pdfFileUrl} fileName={pdfFileName} />
            </ErrorBoundary>
          )}
        </div>

        <div className="border-t bg-background flex items-stretch shrink-0 pb-[env(safe-area-inset-bottom)]">
          {mobileTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setMobileTab(tab.id)}
              className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] transition-colors ${
                mobileTab === tab.id ? "text-primary" : "text-muted-foreground"
              }`}
            >
              <tab.icon className="w-5 h-5" />
              {tab.label}
            </button>
          ))}
        </div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      <div className="flex flex-1 overflow-hidden">
        <ActivityBar
          activeItem={layout.activityItem}
          onItemClick={layout.handleActivityClick}
          items={availableActivityItems}
        />
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="h-9 px-4 bg-muted/50 border-b flex items-center gap-2 shrink-0">
            {breadcrumbs.map((item, idx) => (
              <span key={idx} className="flex items-center gap-2">
                {idx > 0 && <span className="text-muted-foreground text-xs">/</span>}
                {item.href ? (
                  <a href={item.href} className="text-xs font-medium text-primary hover:underline">
                    {item.label}
                  </a>
                ) : (
                  <span className="text-xs text-muted-foreground">{item.label}</span>
                )}
              </span>
            ))}
            <div className="ml-auto flex items-center gap-2">
              {workspaceFeatures.study_plan && (
                <ExamPrepButton
                  courseId={courseId}
                  onActivated={() => openPractice("plan")}
                />
              )}
              <SceneSelector
                courseId={courseId}
                activeTab={!layout.hiddenPanels.has("quiz") ? layout.rightTab : layout.activityItem}
                getCurrentUiState={layout.buildWorkspaceState}
                onSwitch={(_id, result) => layout.applySceneResult(result)}
              />
            </div>
          </div>

          <StatusBar
            courseName={activeCourse?.name || "Loading..."}
            chapterName={contentTree[0]?.title}
            studyTime={studyTime}
            activeGoalTitle={activeGoal?.title}
            activeTaskTitle={activeTask?.title}
            sceneLabel={sceneLabel}
            nextActionTitle={nextAction?.title}
          />

          <AgentFocusStrip
            activeGoalTitle={activeGoal?.title}
            activeTaskTitle={activeTask?.title}
            nextAction={nextAction}
            queueing={queueingNextAction}
            onOpenActivity={openActivityCockpit}
            onQueueNextAction={() => void queueRecommendedTask()}
          />

          {workspaceFeatures.practice && (
            <AutoGenBanner courseId={courseId} onQuizReady={() => openPractice("quiz")} />
          )}
          <NotificationPrompt />

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

            <ResizablePanelGroup groupRef={layout.panelGroupRef} orientation="horizontal" className="flex-1">
              {!layout.hiddenPanels.has("pdf") && (
                <>
                  <ResizablePanel id="pdf" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
                        <FileText className="h-3.5 w-3.5 text-red-500" />
                        <span className="text-xs font-medium text-foreground flex-1 truncate">PDF Viewer</span>
                        <button onClick={() => layout.togglePanel("pdf")} className="text-muted-foreground hover:text-foreground">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <ErrorBoundary>
                        <PdfViewer fileUrl={pdfFileUrl} fileName={pdfFileName} />
                      </ErrorBoundary>
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {workspaceFeatures.notes && !layout.hiddenPanels.has("notes") && (
                <>
                  <ResizablePanel id="notes" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
                        <FileText className="h-3.5 w-3.5 text-primary" />
                        <span className="text-xs font-medium text-foreground flex-1">Agent Notes</span>
                        <button onClick={() => layout.togglePanel("notes")} className="text-muted-foreground hover:text-foreground">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <ErrorBoundary>
                        <NotesPanel courseId={courseId} contentTree={contentTree} />
                      </ErrorBoundary>
                    </div>
                  </ResizablePanel>
                  <ResizableHandle withHandle />
                </>
              )}

              {!layout.hiddenPanels.has("quiz") && (
                <>
                  <ResizablePanel id="quiz" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <div className="border-b px-1 py-1 flex items-center gap-0.5 shrink-0 bg-muted/50 overflow-x-auto">
                        {availableRightTabs.map((tab) => {
                          const meta = RIGHT_TAB_META[tab];
                          const Icon = meta.icon;
                          return (
                            <Button
                              key={tab}
                              variant={layout.rightTab === tab ? "secondary" : "ghost"}
                              size="sm"
                              className="text-xs h-7 px-2"
                              onClick={() => {
                                layout.setRightTab(tab);
                              }}
                            >
                              <Icon className="h-3 w-3 mr-1" />
                              {meta.label}
                            </Button>
                          );
                        })}
                        <div className="flex-1 min-w-2" />
                        <button onClick={() => layout.togglePanel("quiz")} className="text-muted-foreground hover:text-foreground px-1">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      {rightTabContent}
                    </div>
                  </ResizablePanel>
                  {workspaceFeatures.free_qa && <ResizableHandle withHandle />}
                </>
              )}

              {workspaceFeatures.free_qa && !layout.hiddenPanels.has("chat") && (
                <ResizablePanel id="chat" defaultSize={25} minSize={8}>
                  <div className="h-full flex flex-col">
                    <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
                      <MessageSquare className="h-3.5 w-3.5 text-primary" />
                      <span className="text-xs font-medium text-foreground flex-1">Q&A</span>
                      <button onClick={() => layout.togglePanel("chat")} className="text-muted-foreground hover:text-foreground">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <ErrorBoundary>
                      <ChatPanel courseId={courseId} activeTab={layout.activityItem} scene={activeScene} />
                    </ErrorBoundary>
                  </div>
                </ResizablePanel>
              )}
            </ResizablePanelGroup>

            <NLTuningFAB courseId={courseId} />
          </div>

          {hiddenPanels.length > 0 && (
            <div className="h-8 px-3 bg-muted/50 border-t flex items-center gap-2 shrink-0">
              <span className="text-[11px] text-muted-foreground">Hidden:</span>
              {hiddenPanels.map((panelId) => (
                <button
                  key={panelId}
                  onClick={() => layout.togglePanel(panelId)}
                  className="px-2 py-0.5 bg-background border border-border rounded text-[11px] text-muted-foreground hover:border-primary hover:text-primary"
                >
                  {panelId === "pdf"
                    ? "PDF"
                    : panelId === "notes"
                      ? "Notes"
                      : panelId === "quiz"
                        ? RIGHT_TAB_META[layout.rightTab].label
                        : "Chat"} +
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {dialogs}
    </div>
  );
}
