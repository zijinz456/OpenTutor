"use client";

import { useEffect, useMemo, useState, useCallback, Suspense, lazy } from "react";
import { useParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import {
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
import { useT } from "@/lib/i18n-context";

const PracticeSection = lazy(() =>
  import("@/components/sections/practice-section").then((m) => ({ default: m.PracticeSection })),
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

function ContentBlock({ node, depth = 0 }: { node: ContentNode; depth?: number }) {
  const headingLevel = Math.min((node.level ?? 0) + 1, 6);
  const sizeClass =
    headingLevel === 1 ? "text-2xl" :
    headingLevel === 2 ? "text-xl" :
    headingLevel === 3 ? "text-lg" : "text-base";

  return (
    <div className="mb-6" style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : undefined }}>
      <h2 className={`font-semibold mb-3 ${sizeClass}`}>{node.title}</h2>
      {node.content && (
        <MarkdownRenderer
          content={node.content}
          className="prose prose-sm max-w-none dark:prose-invert leading-relaxed"
        />
      )}
      {node.children?.map((child) => (
        <ContentBlock key={child.id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}

function ErrorAnalysis({ items }: { items: WrongAnswer[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No wrong answers recorded for this concept.</p>;
  }
  return (
    <div className="space-y-3">
      {items.slice(0, 5).map((item) => (
        <div key={item.id} className="rounded-lg border border-border p-3">
          <p className="text-sm text-foreground">{item.question ?? "Question"}</p>
          <div className="flex gap-4 mt-2 text-xs">
            <span className="text-destructive">Your answer: {item.user_answer || "—"}</span>
            <span className="text-success">Correct: {item.correct_answer ?? "—"}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function MasteryTimeline({ items }: { items: ReviewItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No mastery data available yet.</p>;
  }
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-3 rounded-lg border border-border p-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{item.concept_label}</p>
            <p className="text-xs text-muted-foreground">
              Stability: {item.stability_days}d
              {item.retrievability != null && ` · Retrievability: ${Math.round(item.retrievability * 100)}%`}
              {item.last_reviewed && ` · Last: ${new Date(item.last_reviewed).toLocaleDateString()}`}
            </p>
          </div>
          <div className="shrink-0">
            <div className="w-16 h-2 bg-muted rounded-full overflow-hidden">
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

export default function ChapterPage() {
  const params = useParams();
  const courseId = params.id as string;
  const nodeId = params.nodeId as string;
  const t = useT();

  const { courses, fetchCourses, activeCourse, setActiveCourse, contentTree, fetchContentTree } = useCourseStore();
  const setSelectedNodeId = useWorkspaceStore((s) => s.setSelectedNodeId);
  const [chatOpen, setChatOpen] = useState(false);
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);

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
      .then((data) => { ttlCache.set("course:health", data, 30_000); setHealth(data); })
      .catch(() => {});
  }, []);

  // Fetch wrong answers and review data scoped to this node
  useEffect(() => {
    // Collect titles from this node and its children for fuzzy matching
    const collectTitles = (n: ContentNode): string[] => {
      const titles = [n.title.toLowerCase()];
      for (const child of n.children ?? []) titles.push(...collectTitles(child));
      return titles;
    };
    const currentNode = findNodeById(contentTree, nodeId);
    const nodeTitles = currentNode ? collectTitles(currentNode) : [];

    listWrongAnswers(courseId)
      .then((items) => {
        if (!items) { setWrongAnswers([]); return; }
        if (nodeTitles.length === 0) { setWrongAnswers(items.slice(0, 10)); return; }
        const filtered = items.filter((item) => {
          const q = (item.question ?? "").toLowerCase();
          return nodeTitles.some((t) => q.includes(t) || t.includes(q.slice(0, 20)));
        });
        setWrongAnswers((filtered.length > 0 ? filtered : items).slice(0, 10));
      })
      .catch(() => {});

    getReviewSession(courseId)
      .then((session) => {
        const allItems = session?.items ?? [];
        if (nodeTitles.length === 0) { setReviewItems(allItems); return; }
        const filtered = allItems.filter((item) => {
          const label = item.concept_label.toLowerCase();
          return nodeTitles.some((t) => label.includes(t) || t.includes(label));
        });
        setReviewItems(filtered.length > 0 ? filtered : allItems);
      })
      .catch(() => {});
  }, [courseId, nodeId, contentTree]);

  // Register action handler
  const handleAction = useCallback((action: ChatAction) => {
    if (action.action === "data_updated") {
      const section = action.value as string;
      if (section) useWorkspaceStore.getState().triggerRefresh(section as "notes" | "practice" | "analytics" | "plan");
    }
  }, []);

  useEffect(() => {
    useChatStore.getState().setOnAction(handleAction);
  }, [handleAction]);

  const course = activeCourse ?? courses.find((c) => c.id === courseId) ?? null;
  const node = useMemo(() => findNodeById(contentTree, nodeId), [contentTree, nodeId]);

  if (!node) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-sm text-muted-foreground animate-pulse">Loading...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <ChapterHeader
        courseId={courseId}
        courseName={course?.name ?? "Course"}
        chapterTitle={node.title}
      />

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-10">
        {/* Notes / Content */}
        <section>
          <ContentBlock node={node} />
        </section>

        {/* Inline Practice */}
        <section className="border-t border-border pt-8">
          <h2 className="text-lg font-semibold mb-4">{t("course.practice")}</h2>
          <div className="rounded-xl border border-border bg-card overflow-hidden min-h-[300px]">
            <Suspense fallback={<div className="p-4 text-sm text-muted-foreground animate-pulse">Loading practice...</div>}>
              <PracticeSection courseId={courseId} showReview={false} aiActionsEnabled={aiActionsEnabled} />
            </Suspense>
          </div>
        </section>

        {/* Error Analysis */}
        {wrongAnswers.length > 0 && (
          <section className="border-t border-border pt-8">
            <h2 className="text-lg font-semibold mb-4">Error Analysis</h2>
            <ErrorAnalysis items={wrongAnswers} />
          </section>
        )}

        {/* Mastery Timeline */}
        {reviewItems.length > 0 && (
          <section className="border-t border-border pt-8">
            <h2 className="text-lg font-semibold mb-4">Mastery Timeline</h2>
            <MasteryTimeline items={reviewItems} />
          </section>
        )}

        {/* Related Chapters / Sub-sections */}
        {node.children && node.children.length > 0 && (
          <section className="border-t border-border pt-8">
            <h2 className="text-lg font-semibold mb-4">Sub-sections</h2>
            <div className="flex flex-col gap-2">
              {node.children.map((child) => (
                <a
                  key={child.id}
                  href={`/course/${courseId}/${child.id}`}
                  className="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-accent/50 transition-colors text-sm"
                >
                  <span className="text-foreground">{child.title}</span>
                </a>
              ))}
            </div>
          </section>
        )}
      </main>

      {/* Chat FAB + Drawer */}
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
