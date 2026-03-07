"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import { getHealthStatus, updateCourseLayout, type ChatAction, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import type { BlockType, BlockSize, LearningMode } from "@/lib/block-system/types";
import { TEMPLATE_LIST, buildLayoutFromMode } from "@/lib/block-system/templates";
import { BLOCK_REGISTRY } from "@/lib/block-system/registry";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { IngestionProgress } from "@/components/shared/ingestion-progress";
import { ContinueLearningCta } from "@/components/course/continue-learning-cta";
import { BlockGrid } from "@/components/blocks/block-grid";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { SearchDialog } from "@/components/shared/search-dialog";
import {
  getUnlockContext,
  incrementSessionCount,
  isBlockUnlocked,
  updateUnlockContext,
} from "@/lib/block-system/feature-unlock";
import { recordSessionVisit } from "@/lib/learner-persona";
import { useT, useTF } from "@/lib/i18n-context";

const MODE_SUGGESTION_COOLDOWN_MS = 12 * 60 * 60 * 1000;

// Check for newly unlockable blocks and suggest them via agent insight
function checkAndSuggestUnlockedBlocks(
  courseId: string,
  totalCourses: number,
  mode: LearningMode | undefined,
  aiActionsEnabled: boolean,
  t: (key: string) => string,
) {
  if (!aiActionsEnabled) return;
  const ctx = { ...getUnlockContext(courseId, totalCourses), mode };
  if ((ctx.sessionCount ?? 0) < 3) return; // Agent insights unlock after 3+ sessions

  const store = useWorkspaceStore.getState();
  const currentBlocks = store.spaceLayout.blocks;
  const suggestedKey = `opentutor_suggested_unlocks_${courseId}`;

  let alreadySuggested: string[] = [];
  try {
    const raw = localStorage.getItem(suggestedKey);
    if (raw) alreadySuggested = JSON.parse(raw);
  } catch { /* ignore */ }

  const UNLOCK_SUGGESTIONS: Array<{ type: BlockType; message: string }> = [
    { type: "knowledge_graph", message: t("course.unlock.knowledgeGraph") },
    { type: "wrong_answers", message: t("course.unlock.wrongAnswers") },
    { type: "forecast", message: t("course.unlock.forecast") },
    { type: "plan", message: t("course.unlock.plan") },
  ];

  for (const suggestion of UNLOCK_SUGGESTIONS) {
    if (!isBlockUnlocked(suggestion.type, ctx).unlocked) continue;
    if (alreadySuggested.includes(suggestion.type)) continue;
    if (currentBlocks.some((b) => b.type === suggestion.type)) continue;

    const blockLabel = BLOCK_REGISTRY[suggestion.type]?.label ?? suggestion.type.replace(/_/g, " ");

    // Add agent insight block suggesting this feature
    store.agentAddBlock(
      "agent_insight",
      {
        insightType: "feature_unlock",
        suggestedBlockType: suggestion.type,
        reason: suggestion.message,
      },
      {
        reason: suggestion.message,
        needsApproval: true,
        dismissible: true,
        approvalCta: `${t("course.unlock.add")} ${blockLabel}`,
      },
    );

    // Mark as suggested so we don't re-suggest
    alreadySuggested.push(suggestion.type);
    try {
      localStorage.setItem(suggestedKey, JSON.stringify(alreadySuggested));
    } catch { /* ignore */ }

    break; // Only suggest one at a time
  }
}

export default function CoursePage() {
  const params = useParams();
  const router = useRouter();
  const t = useT();
  const tf = useTF();
  const courseId = params.id as string;
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );
  const [chatOpen, setChatOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
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
  const spaceMode = useWorkspaceStore((s) => s.spaceLayout.mode);
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
      .catch((e) => console.error("[Course] health check failed:", e));
  }, []);

  // Global search shortcut (Cmd+K / Ctrl+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Track session for progressive complexity + learner persona
  useEffect(() => {
    incrementSessionCount(courseId);
    recordSessionVisit();
  }, [courseId]);

  // Keep source doc count synced for feature unlock logic.
  useEffect(() => {
    if (!blocksInitialized.current) return;
    if (courses.length === 0) return;

    if (contentTree.length > 0) {
      updateUnlockContext(courseId, { sourceDocCount: contentTree.length });
    }
    // After unlock context is updated, check for newly unlockable blocks
    const llmReady = health?.llm_status !== "mock_fallback" && health?.llm_status !== "configuration_required";
    checkAndSuggestUnlockedBlocks(courseId, courses.length, spaceMode, llmReady, t);
  }, [courseId, contentTree.length, courses.length, spaceMode, health?.llm_status, t]);

  const course = activeCourse ?? courses.find((item) => item.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";
  const queueModeSuggestion = useCallback((payload: {
    suggestedMode: LearningMode;
    reason: string;
    approvalCta: string;
    cooldownKey: string;
    signals?: string[];
  }): boolean => {
    const store = useWorkspaceStore.getState();
    const hasPendingModeSuggestion = store.spaceLayout.blocks.some(
      (b) =>
        b.type === "agent_insight" &&
        b.config.insightType === "mode_suggestion" &&
        b.agentMeta?.needsApproval,
    );
    if (hasPendingModeSuggestion) return false;

    const key = `opentutor_mode_suggestion_${courseId}_${payload.suggestedMode}_${payload.cooldownKey}`;
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const lastTs = Number(raw);
        if (!Number.isNaN(lastTs) && Date.now() - lastTs < MODE_SUGGESTION_COOLDOWN_MS) {
          return false;
        }
      }
    } catch {
      // ignore localStorage parse issues
    }

    store.agentAddBlock(
      "agent_insight",
      {
        insightType: "mode_suggestion",
        suggestedMode: payload.suggestedMode,
        reason: payload.reason,
        suggestionSignals: payload.signals ?? [],
      },
      {
        reason: payload.reason,
        dismissible: true,
        needsApproval: true,
        approvalCta: payload.approvalCta,
      },
    );

    try {
      localStorage.setItem(key, String(Date.now()));
    } catch {
      // ignore localStorage write issues
    }
    return true;
  }, [courseId]);

  // Initialize blocks from course metadata or localStorage.
  // Uses a lastCourseId ref to detect course changes and avoid a separate
  // reset effect that could race with this one.
  const lastCourseIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (lastCourseIdRef.current !== courseId) {
      lastCourseIdRef.current = courseId;
      blocksInitialized.current = false;
    }
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

    // Fall back to persisted learning mode in metadata (if present).
    const savedMode = (course?.metadata as Record<string, unknown> | undefined)
      ?.learning_mode as LearningMode | undefined;
    if (savedMode) {
      loadBlocks(buildLayoutFromMode(savedMode));
    }
  }, [courseId, course, loadBlocks]);

  // Persist blocks to localStorage + backend (debounced)
  const persistTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (!blocksInitialized.current || blocks.length === 0) return;
    clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      const layout = useWorkspaceStore.getState().spaceLayout;
      localStorage.setItem(`opentutor_blocks_${courseId}`, JSON.stringify(layout));
      updateCourseLayout(courseId, layout as unknown as Record<string, unknown>).catch((e) => console.error("[Course] layout persist failed:", e));
    }, 2000);
    return () => clearTimeout(persistTimer.current);
  }, [blocks, courseId]);

  // Handle chat actions — including block manipulation
  const handleAction = useCallback((action: ChatAction) => {
    const store = useWorkspaceStore.getState();
    const parseSize = (raw?: string): BlockSize | undefined =>
      raw === "small" || raw === "medium" || raw === "large" || raw === "full"
        ? raw
        : undefined;
    const normalizeTemplateId = (raw?: string): string | undefined =>
      raw
        ? raw.trim().toLowerCase().replace(/\s+/g, "_")
        : undefined;

    if (action.action === "data_updated") {
      const section = action.value as string;
      if (section) store.triggerRefresh(section as "notes" | "practice" | "analytics" | "plan");
    } else if (action.action === "focus_topic") {
      const nodeId = action.value as string | undefined;
      if (nodeId) {
        store.setSelectedNodeId(nodeId);
        router.push(`/course/${courseId}/unit/${nodeId}`);
      }
    } else if (action.action === "add_block") {
      // Supports both:
      // [ACTION:add_block:flashcards:medium]
      // [ACTION:add_block:flashcards] + optional extra=size
      const [typeFromValue, inlineSize] = (action.value ?? "").split(":");
      const type = typeFromValue as BlockType | undefined;
      const size = parseSize(action.extra) ?? parseSize(inlineSize);
      if (type) store.addBlock(type, {}, "agent", size);
    } else if (action.action === "remove_block") {
      if (action.value) store.removeBlockByType(action.value as BlockType);
    } else if (action.action === "reorder_blocks") {
      const types = (action.value ?? "").split(",").filter(Boolean) as BlockType[];
      if (types.length) store.reorderBlocks(types);
    } else if (action.action === "resize_block") {
      // Supports both:
      // [ACTION:resize_block:notes:large]
      // [ACTION:resize_block:notes] + extra=large
      const [typeFromValue, inlineSize] = (action.value ?? "").split(":");
      const targetType = (typeFromValue || action.value) as BlockType | undefined;
      const nextSize = parseSize(action.extra) ?? parseSize(inlineSize);
      const blocks = store.spaceLayout.blocks;
      const target = targetType ? blocks.find((b) => b.type === targetType) : undefined;
      if (target && nextSize) {
        store.resizeBlock(target.id, nextSize);
      }
    } else if (action.action === "apply_template") {
      const templateId = normalizeTemplateId(action.value);
      if (templateId) store.applyBlockTemplate(templateId);
    } else if (action.action === "agent_insight") {
      store.agentAddBlock(
        "agent_insight",
        { insightType: action.value },
        { reason: action.extra || "", dismissible: true },
      );
    } else if (action.action === "set_learning_mode") {
      const mode = action.value as LearningMode;
      if (mode) {
        store.setLearningMode(mode);
        updateUnlockContext(courseId, { mode });
      }
    } else if (action.action === "suggest_mode") {
      const mode = action.value as LearningMode;
      if (mode) {
        store.agentAddBlock(
          "agent_insight",
          { insightType: "mode_suggestion", suggestedMode: mode, reason: action.extra || "" },
          {
            reason: action.extra || tf("course.modeSuggestion.generic", { mode }),
            dismissible: true,
            needsApproval: true,
            approvalCta: t("course.modeSuggestion.switch"),
          },
        );
      }
    }
  }, [courseId, router, t, tf]);

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
                  reason: tf("course.reviewNeeded", { count: urgentItems.length }),
                  dismissible: true,
                },
              );
            }
          }
        })
        .catch((e) => console.error("[Course] LECTOR review check failed:", e));
    });
  }, [course, courseId, aiActionsEnabled, tf]);

  // Agent autonomy: evaluate one mode transition suggestion (Tier-2) using prioritized signals.
  useEffect(() => {
    if (!course || !aiActionsEnabled) return;
    const evalKey = `agent_mode_eval_${courseId}`;
    if (sessionStorage.getItem(evalKey) === "true") return;
    sessionStorage.setItem(evalKey, "true");

    const currentMode = useWorkspaceStore.getState().spaceLayout.mode as LearningMode | undefined;
    if (!currentMode) return;

    import("@/lib/api/progress").then(async ({ listStudyGoals, getCourseProgress }) => {
      const goals = await listStudyGoals(courseId, "active").catch(() => []);
      const now = Date.now();
      const deadlines = goals
        .filter((g) => g.target_date)
        .map((g) => ({
          goal: g,
          daysLeft: Math.ceil((new Date(g.target_date!).getTime() - now) / (1000 * 60 * 60 * 24)),
        }));

      if (deadlines.length > 0) {
        updateUnlockContext(courseId, { hasDeadline: true });
      }

      const upcoming = deadlines
        .filter((d) => d.daysLeft >= 0 && d.daysLeft <= 7)
        .sort((a, b) => a.daysLeft - b.daysLeft)[0];
      const allDeadlinesPassed = deadlines.length > 0 && deadlines.every((d) => d.daysLeft < 0);

      const progress = await getCourseProgress(courseId).catch(() => null);
      const mastery = progress ? Math.round((progress.average_mastery ?? 0) * 100) : null;
      const totalAttempts = progress ? progress.mastered + progress.reviewed + progress.in_progress : 0;
      const errorRatePct =
        progress && totalAttempts > 10
          ? Math.round((progress.in_progress / totalAttempts) * 100)
          : null;

      if (currentMode === "exam_prep" && allDeadlinesPassed) {
        queueModeSuggestion({
          suggestedMode: "maintenance",
          reason: t("course.modeSuggestion.examPassed"),
          approvalCta: t("course.modeSuggestion.switchMaintenance"),
          cooldownKey: "exam_passed",
          signals: [t("course.modeSuggestion.signal.deadlinesPassed")],
        });
        return;
      }

      if (currentMode === "course_following" || currentMode === "self_paced") {
        if (upcoming && errorRatePct != null && errorRatePct > 40) {
          queueModeSuggestion({
            suggestedMode: "exam_prep",
            reason: tf("course.modeSuggestion.errorRateDetailed", {
              rate: errorRatePct,
              days: upcoming.daysLeft,
            }),
            approvalCta: t("course.modeSuggestion.switchExamPrep"),
            cooldownKey: "error_rate",
            signals: [
              tf("course.modeSuggestion.signal.errorRate", { rate: errorRatePct }),
              tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft }),
            ],
          });
          return;
        }

        if (upcoming) {
          queueModeSuggestion({
            suggestedMode: "exam_prep",
            reason: tf("course.modeSuggestion.deadline", {
              title: upcoming.goal.title,
              days: upcoming.daysLeft,
            }),
            approvalCta: t("course.modeSuggestion.switchExamPrep"),
            cooldownKey: "deadline",
            signals: [tf("course.modeSuggestion.signal.deadline", { days: upcoming.daysLeft })],
          });
          return;
        }

        if (mastery != null && mastery >= 85) {
          queueModeSuggestion({
            suggestedMode: "maintenance",
            reason: tf("course.modeSuggestion.mastery", { mastery }),
            approvalCta: t("course.modeSuggestion.switchMaintenance"),
            cooldownKey: "mastery",
            signals: [tf("course.modeSuggestion.signal.mastery", { mastery })],
          });
        }
      }
    }).catch((e) => console.error("[Course] mode evaluator failed:", e));
  }, [course, courseId, aiActionsEnabled, t, tf, queueModeSuggestion]);

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
        .then((result: { greeting: string; course_name: string; suggested_actions?: ChatAction[] }) => {
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
          // Fire suggested actions from greeting
          if (result.suggested_actions?.length) {
            for (const action of result.suggested_actions) {
              handleAction(action);
            }
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
  }, [course, courseId, handleAction]);

  const hasBlocks = blocks.length > 0;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || t("course.defaultTitle")} courseId={courseId} />

      <div className="px-5 pt-4 max-w-5xl mx-auto w-full space-y-2">
        <RuntimeAlert health={health} />
        <IngestionProgress
          courseId={courseId}
          onIngestionComplete={() => {
            const store = useWorkspaceStore.getState();
            if (store.spaceLayout.blocks.length === 0) {
              store.applyBlockTemplate("stem_student");
            }
          }}
        />
      </div>

      <main className="flex-1 max-w-5xl mx-auto w-full px-5 py-8 space-y-6">
        {hasBlocks ? (
          /* Block-based layout */
          <BlockGrid courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
        ) : (
          /* Empty state: choose a template or start from scratch */
          <>
            <ContinueLearningCta courseId={courseId} nodes={contentTree} />

            <section>
              <h2 className="text-lg font-semibold mb-3">{t("course.template.title")}</h2>
              <p className="text-sm text-muted-foreground mb-4">
                {t("course.template.subtitle")}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {TEMPLATE_LIST.map((t) => (
                  <button
                    type="button"
                    key={t.id}
                    onClick={() => applyBlockTemplate(t.id)}
                    className="p-5 rounded-2xl bg-card card-lift text-left group"
                  >
                    <p className="text-sm font-medium text-foreground">{t.name}</p>
                    <p className="text-xs text-muted-foreground mt-1">{t.description}</p>
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {t.blocks
                        .filter((b) => b.type !== "chapter_list")
                        .map((b, i) => (
                          <span
                            key={i}
                            className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground"
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

      {/* Global search */}
      <SearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} courseId={courseId} />
    </div>
  );
}
