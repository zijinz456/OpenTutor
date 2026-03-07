"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useCallback, Suspense, lazy } from "react";
import { useParams, useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import {
  extractQuiz,
  getHealthStatus,
  listWrongAnswers,
  getReviewSession,
  type ChatAction,
  type ContentNode,
  type HealthStatus,
  type WrongAnswer,
  type ReviewItem,
} from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import { ChapterHeader } from "@/components/course/chapter-header";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useT, useTF } from "@/lib/i18n-context";

type TranslateFn = (key: string) => string;

const PracticeSection = lazy(() =>
  import("@/components/sections/practice-section").then((m) => ({ default: m.PracticeSection })),
);
const GraphView = lazy(() =>
  import("@/components/sections/analytics/graph-view").then((m) => ({ default: m.GraphView })),
);

function findNodeById(nodes: ContentNode[], nodeId: string): ContentNode | null {
  for (const node of nodes) {
    if (node.id === nodeId) return node;
    if (node.children?.length) {
      const found = findNodeById(node.children, nodeId);
      if (found) return found;
    }
  }
  return null;
}

function findPathToNode(nodes: ContentNode[], nodeId: string): ContentNode[] {
  const walk = (items: ContentNode[], trail: ContentNode[]): ContentNode[] | null => {
    for (const item of items) {
      const nextTrail = [...trail, item];
      if (item.id === nodeId) return nextTrail;
      if (item.children?.length) {
        const found = walk(item.children, nextTrail);
        if (found) return found;
      }
    }
    return null;
  };
  return walk(nodes, []) ?? [];
}

function collectTitles(node: ContentNode): string[] {
  const titles: string[] = [node.title];
  for (const child of node.children ?? []) {
    titles.push(...collectTitles(child));
  }
  return titles;
}

function buildFocusTerms(node: ContentNode): string[] {
  const tokens = collectTitles(node)
    .flatMap((title) =>
      title
        .toLowerCase()
        .split(/[^a-z0-9\u4e00-\u9fa5]+/)
        .map((part) => part.trim())
        .filter((part) => part.length >= 2),
    )
    .filter((token, idx, arr) => arr.indexOf(token) === idx);

  return tokens.slice(0, 12);
}

function matchesFocus(text: string | null | undefined, terms: string[]): boolean {
  if (!text || terms.length === 0) return false;
  const lower = text.toLowerCase();
  return terms.some((term) => lower.includes(term));
}

function scoreWrongAnswerFocus(item: WrongAnswer, terms: string[]): number {
  if (terms.length === 0) return 0;
  const question = (item.question ?? "").toLowerCase();
  const diagnosis = (item.diagnosis ?? "").toLowerCase();
  const knowledgePoints = (item.knowledge_points ?? []).map((point) => point.toLowerCase());

  let score = 0;
  for (const term of terms) {
    if (question.includes(term)) score += 2;
    if (diagnosis.includes(term)) score += 1;
    for (const point of knowledgePoints) {
      if (point.includes(term) || term.includes(point)) {
        score += 3;
        break;
      }
    }
  }
  return score;
}

interface RankedSignal {
  label: string;
  count: number;
}

interface ErrorPatternSummary {
  diagnoses: RankedSignal[];
  categories: RankedSignal[];
  knowledgePoints: RankedSignal[];
}

interface MasterySummary {
  avgMastery: number;
  avgRetrievability: number;
  urgent: number;
  warning: number;
  stale: number;
}

interface ErrorTrendSummary {
  recent7d: number;
  previous7d: number;
  delta: number;
  direction: "up" | "down" | "flat";
}

type QuizDifficulty = "easy" | "medium" | "hard";

interface DifficultyRecommendation {
  level: QuizDifficulty;
  reasonKey: string;
}

function toDisplayLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = value.trim();
  if (!normalized) return null;
  return normalized.replace(/_/g, " ");
}

function rankSignals(counter: Map<string, number>, limit = 5): RankedSignal[] {
  return [...counter.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([label, count]) => ({ label, count }));
}

function buildErrorPatternSummary(items: WrongAnswer[]): ErrorPatternSummary {
  const diagnosisCounter = new Map<string, number>();
  const categoryCounter = new Map<string, number>();
  const pointCounter = new Map<string, number>();

  for (const item of items) {
    const diagnosis = toDisplayLabel(item.diagnosis ?? item.error_detail?.diagnosis);
    if (diagnosis) diagnosisCounter.set(diagnosis, (diagnosisCounter.get(diagnosis) ?? 0) + 1);

    const category = toDisplayLabel(item.error_category ?? item.error_detail?.category);
    if (category) categoryCounter.set(category, (categoryCounter.get(category) ?? 0) + 1);

    for (const point of item.knowledge_points ?? []) {
      const label = toDisplayLabel(point);
      if (!label) continue;
      pointCounter.set(label, (pointCounter.get(label) ?? 0) + 1);
    }
  }

  return {
    diagnoses: rankSignals(diagnosisCounter),
    categories: rankSignals(categoryCounter),
    knowledgePoints: rankSignals(pointCounter),
  };
}

function buildMasterySummary(items: ReviewItem[]): MasterySummary {
  if (items.length === 0) {
    return {
      avgMastery: 0,
      avgRetrievability: 0,
      urgent: 0,
      warning: 0,
      stale: 0,
    };
  }

  const now = Date.now();
  const avgMastery = Math.round(
    (items.reduce((sum, item) => sum + (item.mastery ?? 0), 0) / items.length) * 100,
  );
  const avgRetrievability = Math.round(
    (items.reduce((sum, item) => sum + (item.retrievability ?? 0), 0) / items.length) * 100,
  );
  const urgent = items.filter((item) => item.urgency === "urgent" || item.urgency === "overdue").length;
  const warning = items.filter((item) => item.urgency === "warning").length;
  const stale = items.filter((item) => {
    if (!item.last_reviewed) return true;
    const last = new Date(item.last_reviewed).getTime();
    if (Number.isNaN(last)) return true;
    return now - last > 14 * 24 * 60 * 60 * 1000;
  }).length;

  return { avgMastery, avgRetrievability, urgent, warning, stale };
}

function buildErrorTrendSummary(items: WrongAnswer[]): ErrorTrendSummary {
  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  let recent7d = 0;
  let previous7d = 0;

  for (const item of items) {
    if (!item.created_at) continue;
    const ts = new Date(item.created_at).getTime();
    if (Number.isNaN(ts)) continue;
    const ageMs = now - ts;
    if (ageMs < 0) continue;
    if (ageMs <= 7 * dayMs) recent7d += 1;
    else if (ageMs <= 14 * dayMs) previous7d += 1;
  }

  const delta = recent7d - previous7d;
  const direction: ErrorTrendSummary["direction"] =
    delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return { recent7d, previous7d, delta, direction };
}

function recommendQuizDifficulty(
  mastery: MasterySummary,
  trend: ErrorTrendSummary,
  wrongCount: number,
): DifficultyRecommendation {
  if (mastery.avgMastery < 55 || mastery.urgent >= 3 || trend.delta >= 2 || wrongCount >= 8) {
    return { level: "easy", reasonKey: "unit.difficulty.reason.recovery" };
  }
  if (mastery.avgMastery < 80 || mastery.warning >= 2 || trend.delta > 0 || wrongCount >= 4) {
    return { level: "medium", reasonKey: "unit.difficulty.reason.balanced" };
  }
  return { level: "hard", reasonKey: "unit.difficulty.reason.challenge" };
}

function modeHintFromDifficulty(level: QuizDifficulty): "course_following" | "self_paced" | "exam_prep" {
  if (level === "hard") return "exam_prep";
  if (level === "easy") return "course_following";
  return "self_paced";
}

function ContentBlock({ node, depth = 0 }: { node: ContentNode; depth?: number }) {
  const headingLevel = Math.min((node.level ?? 0) + 1, 6);
  const sizeClass =
    headingLevel === 1 ? "text-2xl" :
    headingLevel === 2 ? "text-xl" :
    headingLevel === 3 ? "text-lg" : "text-base";

  return (
    <div className="mb-6" style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : undefined }}>
      <h2 className={`font-semibold mb-3 ${sizeClass}`}>{node.title}</h2>
      {node.content ? (
        <MarkdownRenderer
          content={node.content}
          className="prose prose-sm max-w-none dark:prose-invert leading-relaxed"
        />
      ) : null}
      {node.children?.map((child) => (
        <ContentBlock key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

function ErrorAnalysis({ items, t }: { items: WrongAnswer[]; t: TranslateFn }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("unit.error.empty")}</p>;
  }
  return (
    <div className="space-y-3">
      {items.slice(0, 6).map((item) => (
        <div key={item.id} className="rounded-xl bg-muted/30 p-3.5">
          <p className="text-sm text-foreground">{item.question ?? t("unit.questionFallback")}</p>
          <div className="flex gap-4 mt-2 text-xs flex-wrap">
            <span className="text-destructive">{t("unit.error.yourAnswer")}: {item.user_answer || "—"}</span>
            <span className="text-success">{t("unit.error.correctAnswer")}: {item.correct_answer ?? "—"}</span>
          </div>
          {item.diagnosis ? (
            <p className="text-xs text-muted-foreground mt-1">{t("unit.error.diagnosis")}: {item.diagnosis}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function MasteryTimeline({ items, t }: { items: ReviewItem[]; t: TranslateFn }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("unit.mastery.empty")}</p>;
  }
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={`${item.concept_id}-${i}`} className="flex items-center gap-3 rounded-xl bg-muted/30 p-3.5">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{item.concept_label}</p>
            <p className="text-xs text-muted-foreground">
              {t("unit.mastery.stability")}: {item.stability_days}d
              {item.retrievability != null && ` · ${t("unit.mastery.retrievability")}: ${Math.round(item.retrievability * 100)}%`}
              {item.last_reviewed && ` · ${t("unit.mastery.last")}: ${new Date(item.last_reviewed).toLocaleDateString()}`}
            </p>
          </div>
          <div className="shrink-0">
            <div className="w-20 h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-success rounded-full"
                style={{ width: `${Math.round(item.mastery * 100)}%` }}
              />
            </div>
            <p className="text-[10px] text-muted-foreground text-right mt-0.5">
              {Math.round(item.mastery * 100)}%
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function UnitPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params.id as string;
  const nodeId = params.nodeId as string;
  const t = useT();
  const tf = useTF();

  const { courses, fetchCourses, activeCourse, setActiveCourse, contentTree, fetchContentTree } = useCourseStore();
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);
  const triggerRefresh = useWorkspaceStore((s) => s.triggerRefresh);
  const [chatOpen, setChatOpen] = useState(false);
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [trendBaseAnswers, setTrendBaseAnswers] = useState<WrongAnswer[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [loadingSignals, setLoadingSignals] = useState(true);
  const [generatingFocusedQuiz, setGeneratingFocusedQuiz] = useState(false);

  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  useEffect(() => {
    if (courses.length === 0) void fetchCourses();
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) setActiveCourse(course);
  }, [courseId, courses, setActiveCourse]);

  useEffect(() => {
    if (contentTree.length === 0) void fetchContentTree(courseId);
  }, [courseId, contentTree.length, fetchContentTree]);

  useEffect(() => {
    setSelectedNodeId(nodeId);
  }, [nodeId, setSelectedNodeId]);

  useEffect(() => {
    getHealthStatus()
      .then((data) => {
        ttlCache.set("course:health", data, 30_000);
        setHealth(data);
      })
      .catch((e) => console.error("[Unit] health check failed:", e));
  }, []);

  const course = activeCourse ?? courses.find((c) => c.id === courseId) ?? null;
  const node = useMemo(() => findNodeById(contentTree, nodeId), [contentTree, nodeId]);
  const nodePath = useMemo(() => findPathToNode(contentTree, nodeId), [contentTree, nodeId]);
  const parentNode = nodePath.length > 1 ? nodePath[nodePath.length - 2] : null;
  const siblingNodes = useMemo(
    () => (parentNode?.children ?? []).filter((child) => child.id !== nodeId),
    [parentNode, nodeId],
  );
  const focusTerms = useMemo(() => (node ? buildFocusTerms(node) : []), [node]);

  useEffect(() => {
    if (!node) return;
    setLoadingSignals(true);

    listWrongAnswers(courseId)
      .then((items) => {
        if (!items) {
          setWrongAnswers([]);
          return;
        }
        const scored = items
          .map((item) => ({ item, score: scoreWrongAnswerFocus(item, focusTerms) }))
          .sort((a, b) => b.score - a.score);
        const matched = scored.filter((entry) => entry.score > 0).map((entry) => entry.item);
        const focused = matched.length > 0 ? matched : items;
        setTrendBaseAnswers(focused);
        setWrongAnswers(focused.slice(0, 12));
      })
      .catch((e) => {
        console.error("[Unit] wrong answers fetch failed:", e);
        setWrongAnswers([]);
        setTrendBaseAnswers([]);
      });

    getReviewSession(courseId, 30)
      .then((session) => {
        const allItems = session?.items ?? [];
        const filtered = allItems.filter((item) => matchesFocus(item.concept_label, focusTerms));
        setReviewItems((filtered.length > 0 ? filtered : allItems).slice(0, 12));
      })
      .catch((e) => {
        console.error("[Unit] review session fetch failed:", e);
        setReviewItems([]);
      })
      .finally(() => setLoadingSignals(false));
  }, [courseId, focusTerms, node]);

  const handleAction = useCallback((action: ChatAction) => {
    if (action.action === "data_updated") {
      const section = action.value as string;
      if (section) {
        useWorkspaceStore
          .getState()
          .triggerRefresh(section as "notes" | "practice" | "analytics" | "plan");
      }
    }
  }, []);

  useEffect(() => {
    useChatStore.getState().setOnAction(handleAction);
  }, [handleAction]);

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

  const urgentReviews = reviewItems.filter(
    (item) => item.urgency === "urgent" || item.urgency === "overdue",
  ).length;
  const errorPatterns = useMemo(
    () => buildErrorPatternSummary(wrongAnswers),
    [wrongAnswers],
  );
  const masterySummary = useMemo(
    () => buildMasterySummary(reviewItems),
    [reviewItems],
  );
  const errorTrend = useMemo(
    () => buildErrorTrendSummary(trendBaseAnswers),
    [trendBaseAnswers],
  );
  const difficultyRec = useMemo(
    () => recommendQuizDifficulty(masterySummary, errorTrend, trendBaseAnswers.length),
    [masterySummary, errorTrend, trendBaseAnswers.length],
  );
  const quizModeHint = useMemo(
    () => modeHintFromDifficulty(difficultyRec.level),
    [difficultyRec.level],
  );

  if (!node) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-sm text-muted-foreground animate-pulse">{t("general.loading")}</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <ChapterHeader
        courseId={courseId}
        courseName={course?.name ?? t("course.home")}
        chapterTitle={node.title}
      />

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-8">
        <section className="rounded-2xl bg-card card-shadow p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t("unit.path")}:</span>
            {nodePath.map((item, idx) => (
              <span key={item.id} className="inline-flex items-center gap-2">
                {idx > 0 ? <span className="text-muted-foreground">/</span> : null}
                {idx === nodePath.length - 1 ? (
                  <span className="font-medium text-foreground">{item.title}</span>
                ) : (
                  <Link
                    href={`/course/${courseId}/unit/${item.id}`}
                    className="text-brand hover:underline"
                  >
                    {item.title}
                  </Link>
                )}
              </span>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-xl bg-muted/30 p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                {t("unit.parentSiblings")}
              </p>
              {parentNode ? (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">
                    {t("unit.parent")}:{" "}
                    <Link href={`/course/${courseId}/unit/${parentNode.id}`} className="text-brand hover:underline">
                      {parentNode.title}
                    </Link>
                  </p>
                  {siblingNodes.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {siblingNodes.slice(0, 8).map((sibling) => (
                        <Link
                          key={sibling.id}
                          href={`/course/${courseId}/unit/${sibling.id}`}
                          className="text-[11px] px-2 py-1 rounded-full bg-muted text-muted-foreground hover:text-foreground transition-colors"
                        >
                          {sibling.title}
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t("unit.noSiblings")}</p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{t("unit.topLevel")}</p>
              )}
            </div>

            <div className="rounded-xl bg-muted/30 p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                {t("unit.conceptSignals")}
              </p>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {focusTerms.slice(0, 10).map((term) => (
                  <span key={term} className="text-[11px] px-2 py-1 rounded-full bg-brand/10 text-brand">
                    {term}
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {tf("unit.matchedSignals", { wrong: wrongAnswers.length, mastery: reviewItems.length })}
              </p>
            </div>
          </div>
        </section>

        <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-2xl bg-card card-shadow p-4">
            <p className="text-xs text-muted-foreground">{t("unit.subsections")}</p>
            <p className="text-2xl font-semibold mt-1">{node.children?.length ?? 0}</p>
          </div>
          <div className="rounded-2xl bg-card card-shadow p-4">
            <p className="text-xs text-muted-foreground">{t("unit.wrongAnswers")}</p>
            <p className="text-2xl font-semibold mt-1">{wrongAnswers.length}</p>
          </div>
          <div className="rounded-2xl bg-card card-shadow p-4">
            <p className="text-xs text-muted-foreground">{t("unit.urgentReviews")}</p>
            <p className="text-2xl font-semibold mt-1">{urgentReviews}</p>
          </div>
        </section>

        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-2xl bg-card card-shadow p-4">
            <h2 className="text-base font-semibold">{t("unit.errorPattern.title")}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">{t("unit.errorPattern.desc")}</p>

            {wrongAnswers.length === 0 ? (
              <p className="text-sm text-muted-foreground mt-3">{t("unit.errorPattern.empty")}</p>
            ) : (
              <div className="mt-3 space-y-3">
                <div>
                  <p className="text-[11px] text-muted-foreground mb-1">{t("unit.errorPattern.diagnosis")}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {errorPatterns.diagnoses.length > 0 ? errorPatterns.diagnoses.map((item) => (
                      <span
                        key={`diag-${item.label}`}
                        className="text-[11px] px-2 py-1 rounded-full bg-destructive/10 text-destructive"
                      >
                        {item.label} · {item.count}
                      </span>
                    )) : (
                      <span className="text-[11px] text-muted-foreground">{t("unit.none")}</span>
                    )}
                  </div>
                </div>

                <div>
                  <p className="text-[11px] text-muted-foreground mb-1">{t("unit.errorPattern.category")}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {errorPatterns.categories.length > 0 ? errorPatterns.categories.map((item) => (
                      <span
                        key={`cat-${item.label}`}
                        className="text-[11px] px-2 py-1 rounded-full bg-warning/10 text-warning"
                      >
                        {item.label} · {item.count}
                      </span>
                    )) : (
                      <span className="text-[11px] text-muted-foreground">{t("unit.none")}</span>
                    )}
                  </div>
                </div>

                <div>
                  <p className="text-[11px] text-muted-foreground mb-1">{t("unit.errorPattern.knowledgePoint")}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {errorPatterns.knowledgePoints.length > 0 ? errorPatterns.knowledgePoints.map((item) => (
                      <span
                        key={`kp-${item.label}`}
                        className="text-[11px] px-2 py-1 rounded-full bg-brand/10 text-brand"
                      >
                        {item.label} · {item.count}
                      </span>
                    )) : (
                      <span className="text-[11px] text-muted-foreground">{t("unit.none")}</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-2xl bg-card card-shadow p-4">
            <h2 className="text-base font-semibold">{t("unit.nextActions.title")}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">{t("unit.nextActions.desc")}</p>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className="rounded-xl bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.avgMastery")}</p>
                <p className="text-base font-semibold">{masterySummary.avgMastery}%</p>
              </div>
              <div className="rounded-xl bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.avgRetrievability")}</p>
                <p className="text-base font-semibold">{masterySummary.avgRetrievability}%</p>
              </div>
              <div className="rounded-xl bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.warning")}</p>
                <p className="text-base font-semibold">{masterySummary.warning}</p>
              </div>
              <div className="rounded-xl bg-muted/30 p-2.5">
                <p className="text-[11px] text-muted-foreground">{t("unit.masterySummary.stale")}</p>
                <p className="text-base font-semibold">{masterySummary.stale}</p>
              </div>
            </div>

            <div className="mt-2 rounded-xl bg-muted/30 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-muted-foreground">{t("unit.errorTrend.title")}</p>
                <span
                  className={`text-[11px] font-medium ${
                    errorTrend.direction === "up"
                      ? "text-destructive"
                      : errorTrend.direction === "down"
                        ? "text-success"
                        : "text-muted-foreground"
                  }`}
                >
                  {tf(`unit.errorTrend.${errorTrend.direction}`, { count: Math.abs(errorTrend.delta) })}
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {tf("unit.errorTrend.window", {
                  recent: errorTrend.recent7d,
                  previous: errorTrend.previous7d,
                })}
              </p>
            </div>

            <div className="mt-2 rounded-xl bg-muted/30 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-muted-foreground">{t("unit.difficulty.recommended")}</p>
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    difficultyRec.level === "hard"
                      ? "bg-destructive/15 text-destructive"
                      : difficultyRec.level === "medium"
                        ? "bg-warning/15 text-warning"
                        : "bg-success/15 text-success"
                  }`}
                >
                  {t(`unit.difficulty.${difficultyRec.level}`)}
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">{t(difficultyRec.reasonKey)}</p>
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => router.push(`/course/${courseId}/review`)}
              >
                {tf("unit.nextActions.review", { count: masterySummary.urgent })}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => router.push(`/course/${courseId}/practice?tab=quiz&mode=${quizModeHint}&difficulty=${difficultyRec.level}`)}
              >
                {t("unit.nextActions.practice")}
              </Button>
              <Button
                size="sm"
                disabled={!aiActionsEnabled || generatingFocusedQuiz}
                onClick={() => void handleGenerateFocusedQuiz()}
              >
                {generatingFocusedQuiz
                  ? t("unit.generating")
                  : tf("unit.generateFocusedQuizWithDifficulty", { level: t(`unit.difficulty.${difficultyRec.level}`) })}
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-2xl bg-card card-shadow p-5">
          <h2 className="text-lg font-semibold mb-4">{t("course.notes")}</h2>
          <ContentBlock node={node} />
        </section>

        <section className="rounded-2xl bg-card card-shadow overflow-hidden">
          <div className="flex items-center gap-2 px-5 py-3 border-b border-border/60 bg-muted/20">
            <div>
              <h2 className="text-base font-semibold">{t("course.practice")}</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                {t("unit.practice.desc")}
              </p>
            </div>
            <div className="ml-auto">
              <Button
                size="sm"
                variant="outline"
                disabled={!aiActionsEnabled || generatingFocusedQuiz}
                onClick={() => void handleGenerateFocusedQuiz()}
              >
                {generatingFocusedQuiz
                  ? t("unit.generating")
                  : tf("unit.generateFocusedQuizWithDifficulty", { level: t(`unit.difficulty.${difficultyRec.level}`) })}
              </Button>
            </div>
          </div>
          <div className="min-h-[320px]">
            <Suspense fallback={<div className="p-4 text-sm text-muted-foreground animate-pulse">{t("unit.loading.practice")}</div>}>
              <PracticeSection
                courseId={courseId}
                showReview={false}
                aiActionsEnabled={aiActionsEnabled}
                defaultTab="quiz"
              />
            </Suspense>
          </div>
        </section>

        <section className="rounded-2xl bg-card card-shadow overflow-hidden h-[360px]">
          <div className="px-5 py-3 border-b border-border/60 bg-muted/20">
            <h2 className="text-base font-semibold">{t("course.graph")}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t("unit.graph.desc")}
            </p>
          </div>
          <Suspense fallback={<div className="p-4 text-sm text-muted-foreground animate-pulse">{t("unit.loading.graph")}</div>}>
            <GraphView courseId={courseId} focusTerms={focusTerms} maxNodes={24} />
          </Suspense>
        </section>

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
          <section className="rounded-2xl bg-card card-shadow p-5">
            <h2 className="text-lg font-semibold mb-4">{t("unit.subsections")}</h2>
            <div className="flex flex-col gap-2">
              {node.children.map((child) => (
                <Link
                  key={child.id}
                  href={`/course/${courseId}/unit/${child.id}`}
                  className="flex items-center gap-3 p-3.5 rounded-xl bg-muted/30 hover:bg-accent/50 transition-colors text-sm"
                >
                  <span className="text-foreground">{child.title}</span>
                </Link>
              ))}
            </div>
          </section>
        ) : null}
      </main>

      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
