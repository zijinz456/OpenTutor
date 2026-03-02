"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
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
import { getFilesByCourseId, getFileUrl, queueNextAction as queueNextActionRequest } from "@/lib/api";
import { SceneSelector } from "@/components/scene/scene-selector";
import { PreferenceConfirmDialog } from "@/components/preference/preference-confirm-dialog";
import { useSceneStore } from "@/store/scene";
import { toast } from "sonner";
import { ErrorBoundary } from "@/components/error-boundary";
import { useActivityPolling } from "@/hooks/use-activity-polling";
import { useIsMobile } from "@/hooks/use-mobile";
import { ExamPrepButton } from "@/components/course/exam-prep-button";
import { useLocale, useT } from "@/lib/i18n-context";
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

function getRightTabLabel(tab: RightTab, t: (key: string) => string) {
  if (tab === "quiz") return t("course.quiz");
  if (tab === "flashcards") return t("course.cards");
  if (tab === "progress") return t("course.stats");
  if (tab === "graph") return t("course.graph");
  if (tab === "review") return t("course.review");
  if (tab === "plan") return t("course.plan");
  if (tab === "activity") return t("course.activity");
  return t("course.profile");
}

/* ---- Shared panel header ---- */
function PanelHeader({ title, onClose, actions }: { title: string; onClose: () => void; actions?: React.ReactNode }) {
  return (
    <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted/50">
      <span className="text-xs font-medium text-foreground flex-1 truncate">{title}</span>
      {actions}
      <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground text-xs">
        x
      </button>
    </div>
  );
}

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;
  const isMobile = useIsMobile();
  const t = useT();
  const { locale } = useLocale();

  const { activeCourse, setActiveCourse, courses, fetchCourses, contentTree } = useCourseStore();
  const { activeScene } = useSceneStore();
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
        workspaceFeatures.notes ? { id: "notes", title: t("course.notes") } : null,
        (workspaceFeatures.practice || workspaceFeatures.wrong_answer || workspaceFeatures.study_plan)
          ? { id: "practice", title: t("course.practice") }
          : null,
        workspaceFeatures.free_qa ? { id: "chat", title: t("course.chat") } : null,
        { id: "progress", title: t("course.progress") },
        { id: "activity", title: t("course.activity") },
        { id: "profile", title: t("course.profile") },
      ].filter((item): item is { id: string; title: string } => Boolean(item)),
    [t, workspaceFeatures],
  );
  const layout = useWorkspaceLayout(courseId, workspaceFeatures);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [mobileTab, setMobileTab] = useState<"chat" | "notes" | "practice" | "pdf">("chat");
  const [pdfFileUrl, setPdfFileUrl] = useState<string | undefined>();
  const [pdfFileName, setPdfFileName] = useState<string | undefined>();
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
      localStorage.removeItem(promptKey);
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
      toast.success(locale === "zh" ? `${t("course.queueSuccess")}：${task.title}` : `${t("course.queueSuccess")}: ${task.title}`);
      openActivityCockpit();
      await refresh();
    } catch (error) {
      toast.error((error as Error).message || t("course.queueError"));
    } finally {
      setQueueingNextAction(false);
    }
  }, [courseId, locale, nextAction, openActivityCockpit, refresh, t]);

  const breadcrumbs = useMemo(
    () => [
      { label: activeCourse?.name || t("nav.courses"), href: "/" },
      ...(contentTree.length > 0 ? [{ label: contentTree[0]?.title || t("course.chapter") }] : []),
    ],
    [activeCourse?.name, contentTree, t],
  );

  const mobileTabs = useMemo(
    () =>
      [
        workspaceFeatures.free_qa ? { id: "chat" as const, label: t("course.chat") } : null,
        workspaceFeatures.notes ? { id: "notes" as const, label: t("course.notes") } : null,
        availableRightTabs.length > 0 ? { id: "practice" as const, label: t("course.practice") } : null,
        { id: "pdf" as const, label: t("course.pdf") },
      ].filter(
        (tab): tab is { id: "chat" | "notes" | "practice" | "pdf"; label: string } => Boolean(tab),
      ),
    [availableRightTabs.length, t, workspaceFeatures.free_qa, workspaceFeatures.notes],
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
        return (
          <Button
            key={tab}
            data-testid={`right-tab-${tab}`}
            variant={layout.rightTab === tab ? "secondary" : "ghost"}
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => {
              layout.setRightTab(tab);
            }}
          >
            {getRightTabLabel(tab, t)}
          </Button>
        );
      })}
    </div>
  );

  /* ---- Mobile layout ---- */
  if (isMobile) {
    return (
      <div className="h-screen flex flex-col bg-background">
        <div className="h-11 px-3 bg-muted/50 border-b flex items-center gap-2 shrink-0">
          <Link href="/" className="text-xs font-medium text-primary truncate max-w-[40%]">
            {activeCourse?.name || t("nav.courses")}
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
            >
              {t("course.upload")}
            </button>
          </div>
        </div>

        {workspaceFeatures.practice && (
          <AutoGenBanner courseId={courseId} onQuizReady={() => openPractice("quiz")} />
        )}

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
              className={`flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors ${
                mobileTab === tab.id ? "text-primary" : "text-muted-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {dialogs}
      </div>
    );
  }

  /* ---- Desktop layout ---- */
  return (
    <div className="h-screen flex flex-col bg-background">
      <div className="flex flex-1 overflow-hidden">
        <ActivityBar
          activeItem={layout.activityItem}
          onItemClick={layout.handleActivityClick}
          items={availableActivityItems}
        />
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Top bar: breadcrumb + controls + upload */}
          <div className="h-10 px-4 bg-muted/50 border-b flex items-center gap-2 shrink-0">
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
              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                data-testid="workspace-upload-trigger"
                className="h-7 px-3 rounded-md bg-background border border-border text-xs font-medium text-foreground hover:border-primary hover:text-primary"
              >
                {t("course.upload")}
              </button>
            </div>
          </div>

          {/* Collapsible agent focus strip */}
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

          {/* Panels */}
          <div className="flex flex-1 overflow-hidden">
            <ResizablePanelGroup groupRef={layout.panelGroupRef} orientation="horizontal" className="flex-1">
              {!layout.hiddenPanels.has("pdf") && (
                <>
                  <ResizablePanel id="pdf" defaultSize={25} minSize={8}>
                    <div className="h-full flex flex-col">
                      <PanelHeader title={t("course.pdfViewer")} onClose={() => layout.togglePanel("pdf")} />
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
                      <PanelHeader title={t("course.agentNotes")} onClose={() => layout.togglePanel("notes")} />
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
                          return (
                            <Button
                              key={tab}
                              data-testid={`right-tab-${tab}`}
                              variant={layout.rightTab === tab ? "secondary" : "ghost"}
                              size="sm"
                              className="text-xs h-7 px-2"
                              onClick={() => {
                                layout.setRightTab(tab);
                              }}
                            >
                              {getRightTabLabel(tab, t)}
                            </Button>
                          );
                        })}
                        <div className="flex-1 min-w-2" />
                        <button type="button" onClick={() => layout.togglePanel("quiz")} className="text-muted-foreground hover:text-foreground px-1 text-xs">
                          x
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
                    <PanelHeader title={t("course.qa")} onClose={() => layout.togglePanel("chat")} />
                    <ErrorBoundary>
                      <ChatPanel courseId={courseId} activeTab={layout.activityItem} scene={activeScene} />
                    </ErrorBoundary>
                  </div>
                </ResizablePanel>
              )}
            </ResizablePanelGroup>

            <NLTuningFAB courseId={courseId} />
          </div>

          {/* Hidden panels restore bar */}
          {hiddenPanels.length > 0 && (
            <div className="h-8 px-3 bg-muted/50 border-t flex items-center gap-2 shrink-0">
              <span className="text-[11px] text-muted-foreground">{t("course.hidden")}</span>
              {hiddenPanels.map((panelId) => (
                <button
                  type="button"
                  key={panelId}
                  onClick={() => layout.togglePanel(panelId)}
                  className="px-2 py-0.5 bg-background border border-border rounded text-[11px] text-muted-foreground hover:border-primary hover:text-primary"
                >
                  {panelId === "pdf"
                    ? t("course.pdf")
                    : panelId === "notes"
                      ? t("course.notes")
                      : panelId === "quiz"
                        ? getRightTabLabel(layout.rightTab, t)
                        : t("course.chat")} +
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
