"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import { extractQuiz } from "@/lib/api";
import { ChapterHeader } from "@/components/course/chapter-header";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { toast } from "sonner";
import { useT, useTF } from "@/lib/i18n-context";

import { ErrorBoundary } from "@/components/shared/error-boundary";
import { useUnitData } from "./_components/use-unit-data";
import { ContentBlock } from "./_components/content-block";
import { ErrorAnalysis, ErrorPatternSection } from "./_components/error-analysis";
import { MasteryTimeline, NextActionsSection } from "./_components/mastery-timeline";
import { UnitNavigation, SubsectionsNav } from "./_components/unit-navigation";
import { StatsRow } from "./_components/stats-row";
import { PracticePanel } from "./_components/practice-panel";
import { GraphPanel } from "./_components/graph-panel";

export default function UnitPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params.id as string;
  const nodeId = params.nodeId as string;
  const t = useT();
  const tf = useTF();
  const triggerRefresh = useWorkspaceStore((s) => s.triggerRefresh);
  const [chatOpen, setChatOpen] = useState(false);
  const [generatingFocusedQuiz, setGeneratingFocusedQuiz] = useState(false);

  // Track last visited node for continue-learning CTA
  useEffect(() => {
    try { localStorage.setItem(`opentutor_last_node_${courseId}`, nodeId); } catch {}
  }, [courseId, nodeId]);

  const {
    course, node, nodePath, parentNode, siblingNodes, focusTerms,
    wrongAnswers, reviewItems, loadingSignals, aiActionsEnabled,
    errorPatterns, masterySummary, errorTrend, difficultyRec, quizModeHint, urgentReviews,
  } = useUnitData(courseId, nodeId);

  const handleGenerateFocusedQuiz = async () => {
    setGeneratingFocusedQuiz(true);
    try {
      const res = await extractQuiz(courseId, nodeId, quizModeHint, difficultyRec.level);
      triggerRefresh("practice");
      toast.success(tf("unit.focusedQuiz.generated", { count: res.problems_created }));
    } catch (error) {
      toast.error((error as Error).message || t("unit.focusedQuiz.failed"));
    } finally {
      setGeneratingFocusedQuiz(false);
    }
  };

  if (!node) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-sm text-muted-foreground animate-pulse">{t("general.loading")}</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <ChapterHeader courseId={courseId} courseName={course?.name ?? t("course.home")} chapterTitle={node.title} />

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-8">
        <UnitNavigation courseId={courseId} nodePath={nodePath} parentNode={parentNode} siblingNodes={siblingNodes} focusTerms={focusTerms} wrongAnswerCount={wrongAnswers.length} reviewItemCount={reviewItems.length} t={t} tf={tf} />

        <StatsRow subsectionCount={node.children?.length ?? 0} wrongAnswerCount={wrongAnswers.length} urgentReviewCount={urgentReviews} t={t} />

        <ErrorBoundary section="error analysis">
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ErrorPatternSection wrongAnswers={wrongAnswers} errorPatterns={errorPatterns} t={t} />
            <NextActionsSection courseId={courseId} masterySummary={masterySummary} errorTrend={errorTrend} difficultyRec={difficultyRec} quizModeHint={quizModeHint} aiActionsEnabled={aiActionsEnabled} generatingFocusedQuiz={generatingFocusedQuiz} onGenerateFocusedQuiz={() => void handleGenerateFocusedQuiz()} onNavigate={(path) => router.push(path)} t={t} tf={tf} />
          </section>
        </ErrorBoundary>

        <ErrorBoundary section="notes">
          <section className="rounded-2xl bg-card card-shadow p-5">
            <h2 className="text-lg font-semibold mb-4">{t("course.notes")}</h2>
            <ContentBlock node={node} />
          </section>
        </ErrorBoundary>

        <ErrorBoundary section="practice">
          <PracticePanel courseId={courseId} difficultyLevel={difficultyRec.level} aiActionsEnabled={aiActionsEnabled} generatingFocusedQuiz={generatingFocusedQuiz} onGenerateFocusedQuiz={() => void handleGenerateFocusedQuiz()} t={t} tf={tf} />
        </ErrorBoundary>

        <ErrorBoundary section="knowledge graph">
          <GraphPanel courseId={courseId} focusTerms={focusTerms} t={t} />
        </ErrorBoundary>

        <section className="rounded-2xl bg-card card-shadow p-5">
          <h2 className="text-lg font-semibold mb-4">{t("unit.errorAnalysis")}</h2>
          {loadingSignals ? (
            <p className="text-sm text-muted-foreground animate-pulse">{t("unit.loading.errorSignals")}</p>
          ) : (
            <ErrorAnalysis items={wrongAnswers} t={t} />
          )}
        </section>

        <section className="rounded-2xl bg-card card-shadow p-5">
          <h2 className="text-lg font-semibold mb-4">{t("unit.masteryTimeline")}</h2>
          {loadingSignals ? (
            <p className="text-sm text-muted-foreground animate-pulse">{t("unit.loading.masteryTimeline")}</p>
          ) : (
            <MasteryTimeline items={reviewItems} t={t} />
          )}
        </section>

        {node.children && node.children.length > 0 ? (
          <SubsectionsNav courseId={courseId} subsections={node.children} t={t} />
        ) : null}
      </main>

      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
