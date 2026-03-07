"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import { getHealthStatus, type ChatAction, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import type { BlockType, LearningMode } from "@/lib/block-system/types";
import { TEMPLATE_LIST } from "@/lib/block-system/templates";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { IngestionProgress } from "@/components/shared/ingestion-progress";
import { ContinueLearningCta } from "@/components/course/continue-learning-cta";
import { BlockGrid } from "@/components/blocks/block-grid";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { incrementSessionCount, updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { recordSessionVisit } from "@/lib/learner-persona";

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );
  const [chatOpen, setChatOpen] = useState(false);
  const blocksInitialized = useRef(false);

  const {
    activeCourse,
    setActiveCourse,
    courses,
    fetchCourses,
    contentTree,
    fetchContentTree,
    fetchIngestionJobs,
  } = useCourseStore();

  const blocks = useWorkspaceStore((s) => s.spaceLayout.blocks);
  const applyBlockTemplate = useWorkspaceStore((s) => s.applyBlockTemplate);
  const loadBlocks = useWorkspaceStore((s) => s.loadBlocks);

  // Load courses
  useEffect(() => {
    if (courses.length === 0) void fetchCourses();
  }, [courses.length, fetchCourses]);

  // Set active course
  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) setActiveCourse(course);
  }, [courseId, courses, setActiveCourse]);

  // Load content tree and ingestion jobs
  useEffect(() => {
    void fetchContentTree(courseId);
    void fetchIngestionJobs(courseId);
  }, [courseId, fetchContentTree, fetchIngestionJobs]);

  // Health check
  useEffect(() => {
    getHealthStatus()
      .then((data) => {
        ttlCache.set("course:health", data, 30_000);
        setHealth(data);
      })
      .catch(() => {});
  }, []);

  // Track session for progressive complexity + learner persona
  useEffect(() => {
    incrementSessionCount(courseId);
    recordSessionVisit();
    // Update source doc count from content tree
    const tree = useCourseStore.getState().contentTree;
    if (tree.length > 0) {
      updateUnlockContext(courseId, { sourceDocCount: tree.length });
    }
  }, [courseId]);

  const course = activeCourse ?? courses.find((item) => item.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  // Initialize blocks from course metadata or localStorage
  useEffect(() => {
    if (blocksInitialized.current) return;
    blocksInitialized.current = true;

    // Try localStorage first
    const saved = localStorage.getItem(`opentutor_blocks_${courseId}`);
    if (saved) {
      try {
        loadBlocks(JSON.parse(saved));
        return;
      } catch { /* ignore */ }
    }

    // Try course metadata
    const savedLayout = (course?.metadata as Record<string, unknown> | undefined)?.spaceLayout;
    if (savedLayout && typeof savedLayout === "object") {
      try {
        loadBlocks(savedLayout as Parameters<typeof loadBlocks>[0]);
        return;
      } catch { /* ignore */ }
    }
  }, [courseId, course, loadBlocks]);

  // Reset on courseId change
  useEffect(() => {
    blocksInitialized.current = false;
  }, [courseId]);

  // Persist blocks to localStorage (debounced)
  const persistTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (!blocksInitialized.current || blocks.length === 0) return;
    clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      const layout = useWorkspaceStore.getState().spaceLayout;
      localStorage.setItem(`opentutor_blocks_${courseId}`, JSON.stringify(layout));
    }, 1000);
    return () => clearTimeout(persistTimer.current);
  }, [blocks, courseId]);

  // Handle chat actions — including block manipulation
  const handleAction = useCallback((action: ChatAction) => {
    const store = useWorkspaceStore.getState();

    if (action.action === "data_updated") {
      const section = action.value as string;
      if (section) store.triggerRefresh(section as "notes" | "practice" | "analytics" | "plan");
    } else if (action.action === "focus_topic") {
      const nodeId = action.value as string | undefined;
      if (nodeId) store.setSelectedNodeId(nodeId);
    } else if (action.action === "add_block") {
      const [type] = (action.value ?? "").split(":");
      if (type) store.addBlock(type as BlockType, {}, "agent");
    } else if (action.action === "remove_block") {
      if (action.value) store.removeBlockByType(action.value as BlockType);
    } else if (action.action === "reorder_blocks") {
      const types = (action.value ?? "").split(",").filter(Boolean) as BlockType[];
      if (types.length) store.reorderBlocks(types);
    } else if (action.action === "resize_block") {
      const blocks = store.spaceLayout.blocks;
      const target = blocks.find((b) => b.type === action.value);
      if (target && action.extra) {
        store.resizeBlock(target.id, action.extra as "small" | "medium" | "large" | "full");
      }
    } else if (action.action === "apply_template") {
      if (action.value) store.applyBlockTemplate(action.value);
    } else if (action.action === "agent_insight") {
      store.agentAddBlock(
        "agent_insight",
        { insightType: action.value },
        { reason: action.extra || "", dismissible: true },
      );
    } else if (action.action === "set_learning_mode") {
      const mode = action.value as LearningMode;
      if (mode) store.setLearningMode(mode);
    } else if (action.action === "suggest_mode") {
      const mode = action.value as LearningMode;
      if (mode) {
        store.agentAddBlock(
          "agent_insight",
          { insightType: "mode_suggestion", suggestedMode: mode, reason: action.extra || "" },
          {
            reason: action.extra || `Suggested switching to ${mode} mode`,
            dismissible: true,
            needsApproval: true,
            approvalCta: "Switch Mode",
          },
        );
      }
    }
  }, []);

  useEffect(() => {
    useChatStore.getState().setOnAction(handleAction);
  }, [handleAction]);

  // Agent autonomy: check LECTOR review on page load
  useEffect(() => {
    if (!course || !aiActionsEnabled) return;
    const checkKey = `agent_review_check_${courseId}`;
    if (sessionStorage.getItem(checkKey) === "true") return;
    sessionStorage.setItem(checkKey, "true");

    import("@/lib/api/progress").then(({ getReviewSession }) => {
      getReviewSession(courseId)
        .then((result) => {
          const urgentItems = result?.items?.filter(
            (item) => item.urgency === "urgent" || item.urgency === "overdue",
          ) ?? [];
          if (urgentItems.length > 0) {
            const store = useWorkspaceStore.getState();
            const hasInsight = store.spaceLayout.blocks.some(
              (b) => b.type === "agent_insight" && b.config.insightType === "review_needed",
            );
            if (!hasInsight) {
              store.agentAddBlock(
                "agent_insight",
                { insightType: "review_needed" },
                {
                  reason: `${urgentItems.length} concept${urgentItems.length > 1 ? "s" : ""} at risk of fading`,
                  dismissible: true,
                },
              );
            }
          }
        })
        .catch(() => {});
    });
  }, [course, courseId, aiActionsEnabled]);

  // Agent autonomy: suggest mode switch when deadline approaches (Tier 2)
  useEffect(() => {
    if (!course || !aiActionsEnabled) return;
    const modeKey = `agent_mode_check_${courseId}`;
    if (sessionStorage.getItem(modeKey) === "true") return;
    sessionStorage.setItem(modeKey, "true");

    const currentMode = useWorkspaceStore.getState().spaceLayout.mode as string | undefined;
    if (currentMode === "exam_prep" || currentMode === "maintenance") return;

    import("@/lib/api/progress").then(({ listStudyGoals }) => {
      listStudyGoals(courseId, "active")
        .then((goals) => {
          // Track hasDeadline for feature-unlock
          if (goals.some((g) => g.target_date)) {
            updateUnlockContext(courseId, { hasDeadline: true });
          }
          const now = Date.now();
          const urgentGoal = goals.find((g) => {
            if (!g.target_date) return false;
            const daysUntil = (new Date(g.target_date).getTime() - now) / (1000 * 60 * 60 * 24);
            return daysUntil >= 0 && daysUntil <= 7;
          });
          if (urgentGoal) {
            const store = useWorkspaceStore.getState();
            const hasInsight = store.spaceLayout.blocks.some(
              (b) => b.type === "agent_insight" && b.config.insightType === "mode_suggestion",
            );
            if (!hasInsight) {
              const daysLeft = Math.ceil(
                (new Date(urgentGoal.target_date!).getTime() - now) / (1000 * 60 * 60 * 24),
              );
              store.agentAddBlock(
                "agent_insight",
                { insightType: "mode_suggestion", suggestedMode: "exam_prep", reason: `${urgentGoal.title} in ${daysLeft}d` },
                {
                  reason: `"${urgentGoal.title}" is due in ${daysLeft} day${daysLeft !== 1 ? "s" : ""}. Switch to Exam Prep mode?`,
                  dismissible: true,
                  needsApproval: true,
                  approvalCta: "Switch to Exam Prep",
                },
              );
            }
          }
        })
        .catch(() => {});
    });
  }, [course, courseId, aiActionsEnabled]);

  // Consume init prompt if any
  useEffect(() => {
    const promptKey = `course_init_prompt_${courseId}`;
    const consumedKey = `course_init_prompt_consumed_${courseId}`;
    const initPrompt = localStorage.getItem(promptKey);
    const alreadyConsumed = sessionStorage.getItem(consumedKey) === "true";
    if (initPrompt && !alreadyConsumed) {
      sessionStorage.setItem(consumedKey, "true");
      localStorage.removeItem(promptKey);
      setChatOpen(true);
      const timer = setTimeout(() => {
        void useChatStore.getState().sendMessage(courseId, initPrompt);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [courseId]);

  // AI proactive greeting
  useEffect(() => {
    if (!course) return;
    const greetingKey = `greeting_shown_${courseId}`;
    if (sessionStorage.getItem(greetingKey) === "true") return;

    const chatState = useChatStore.getState();
    const existing = chatState.messagesByCourse[courseId];
    if (existing && existing.length > 0) return;

    sessionStorage.setItem(greetingKey, "true");

    import("@/lib/api/chat").then(({ getChatGreeting }) => {
      getChatGreeting(courseId)
        .then((result) => {
          const store = useChatStore.getState();
          const msgs = store.messagesByCourse[courseId] || [];
          if (msgs.length === 0) {
            const greetingMsg = {
              id: `greeting-${courseId}`,
              role: "assistant" as const,
              content: result.greeting,
              timestamp: new Date(),
            };
            useChatStore.setState((s) => ({
              messagesByCourse: { ...s.messagesByCourse, [courseId]: [greetingMsg] },
              messages: s.activeCourseId === courseId ? [greetingMsg] : s.messages,
            }));
          }
        })
        .catch(() => {
          const welcome = (course.metadata as Record<string, unknown> | undefined)
            ?.welcome_message as string | undefined;
          if (!welcome) return;
          const store = useChatStore.getState();
          const msgs = store.messagesByCourse[courseId] || [];
          if (msgs.length === 0) {
            const welcomeMsg = {
              id: `welcome-${courseId}`,
              role: "assistant" as const,
              content: welcome,
              timestamp: new Date(),
            };
            useChatStore.setState((s) => ({
              messagesByCourse: { ...s.messagesByCourse, [courseId]: [welcomeMsg] },
              messages: s.activeCourseId === courseId ? [welcomeMsg] : s.messages,
            }));
          }
        });
    });
  }, [course, courseId]);

  const hasBlocks = blocks.length > 0;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || "Course"} courseId={courseId} />

      <div className="px-4 pt-3 max-w-5xl mx-auto w-full space-y-2">
        <RuntimeAlert health={health} />
        <IngestionProgress courseId={courseId} />
      </div>

      <main className="flex-1 max-w-5xl mx-auto w-full px-4 py-6 space-y-6">
        {hasBlocks ? (
          /* Block-based layout */
          <BlockGrid courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
        ) : (
          /* Empty state: choose a template or start from scratch */
          <>
            <ContinueLearningCta courseId={courseId} nodes={contentTree} />

            <section>
              <h2 className="text-lg font-semibold mb-3">Choose a template</h2>
              <p className="text-sm text-muted-foreground mb-4">
                Pick a layout to get started. Your AI tutor will customize it as you learn.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {TEMPLATE_LIST.map((t) => (
                  <button
                    type="button"
                    key={t.id}
                    onClick={() => applyBlockTemplate(t.id)}
                    className="p-4 rounded-xl border border-border bg-card hover:border-brand/40 hover:bg-brand-muted/20 transition-colors text-left"
                  >
                    <p className="text-sm font-medium text-foreground">{t.name}</p>
                    <p className="text-xs text-muted-foreground mt-1">{t.description}</p>
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {t.blocks
                        .filter((b) => b.type !== "chapter_list")
                        .map((b, i) => (
                          <span
                            key={i}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                          >
                            {b.type.replace("_", " ")}
                          </span>
                        ))}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          </>
        )}
      </main>

      {/* Chat FAB + Drawer */}
      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatDrawer courseId={courseId} open={chatOpen} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
