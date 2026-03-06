"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useCourseStore } from "@/store/course";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore, type SectionId } from "@/store/workspace";
import { resolveWorkspaceFeatures } from "@/lib/course-config";
import { getHealthStatus, updateCourseLayout, type ChatAction, type HealthStatus } from "@/lib/api";
import { ttlCache } from "@/lib/cache";
import {
  DEFAULT_LAYOUT,
  LAYOUT_PRESETS,
  getVisibleSections,
  type PresetId,
  type WorkspaceLayout,
} from "@/lib/layout-presets";
import { AppShell } from "@/components/shell/app-shell";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { CourseTree } from "@/components/course-tree/course-tree";
import { ChatView } from "@/components/chat/chat-view";
import { SectionContainer } from "@/components/sections/section-container";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { IngestionProgress } from "@/components/shared/ingestion-progress";

export default function CoursePage() {
  const params = useParams();
  const courseId = params.id as string;
  const [health, setHealth] = useState<HealthStatus | null>(
    () => ttlCache.get<HealthStatus>("course:health") ?? null,
  );

  const {
    activeCourse,
    setActiveCourse,
    courses,
    fetchCourses,
    fetchIngestionJobs,
  } = useCourseStore();
  const layout = useWorkspaceStore((s) => s.layout);
  const setLayout = useWorkspaceStore((s) => s.setLayout);
  const applyPreset = useWorkspaceStore((s) => s.applyPreset);
  const toggleLayoutSection = useWorkspaceStore((s) => s.toggleLayoutSection);

  const layoutInitialized = useRef(false);

  useKeyboardShortcuts();

  useEffect(() => {
    if (courses.length === 0) {
      void fetchCourses();
    }
  }, [courses.length, fetchCourses]);

  useEffect(() => {
    const course = courses.find((c) => c.id === courseId);
    if (course) {
      setActiveCourse(course);
    }
  }, [courseId, courses, setActiveCourse]);

  useEffect(() => {
    void fetchIngestionJobs(courseId);
  }, [courseId, fetchIngestionJobs]);

  useEffect(() => {
    getHealthStatus()
      .then((data) => {
        ttlCache.set("course:health", data, 30_000);
        setHealth(data);
      })
      .catch(() => {});
  }, []);

  const course = activeCourse ?? courses.find((item) => item.id === courseId) ?? null;
  const aiActionsEnabled =
    health?.llm_status !== "mock_fallback" &&
    health?.llm_status !== "configuration_required";

  // Load layout from course metadata (once per course)
  useEffect(() => {
    if (!course || layoutInitialized.current) return;
    layoutInitialized.current = true;

    const savedLayout = course.metadata?.layout as WorkspaceLayout | undefined;
    if (savedLayout?.sections) {
      setLayout(savedLayout);
    } else {
      // Fall back to feature flags for backward compatibility
      const features = resolveWorkspaceFeatures(course.metadata);
      const compat: WorkspaceLayout = {
        ...DEFAULT_LAYOUT,
        sections: DEFAULT_LAYOUT.sections.map((s) => {
          if (s.type === "notes") return { ...s, visible: features.notes };
          if (s.type === "practice") return { ...s, visible: features.practice };
          if (s.type === "plan") return { ...s, visible: features.study_plan };
          return s;
        }),
        chat_visible: features.free_qa,
      };
      setLayout(compat);
    }
  }, [course, setLayout]);

  // Reset layout initialization when courseId changes
  useEffect(() => {
    layoutInitialized.current = false;
  }, [courseId]);

  const visibleSections = useMemo<SectionId[]>(
    () => getVisibleSections(layout),
    [layout],
  );

  // Persist layout changes to backend (debounced)
  const persistTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (!course || !layoutInitialized.current) return;
    clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => {
      void updateCourseLayout(courseId, layout as unknown as Record<string, unknown>);
    }, 1000);
    return () => clearTimeout(persistTimer.current);
  }, [layout, courseId, course]);

  // Handle chat actions (layout changes from AI)
  const handleAction = useCallback(
    (action: ChatAction) => {
      if (action.action === "set_layout_preset") {
        const presetId = action.value as PresetId;
        if (LAYOUT_PRESETS[presetId]) {
          applyPreset(presetId);
        }
      } else if (action.action === "toggle_section") {
        const [sectionId, visibility] = (action.value ?? "").split(":");
        if (sectionId) {
          toggleLayoutSection(sectionId as SectionId, visibility !== "hide");
        }
      } else if (action.action === "data_updated") {
        const section = action.value as SectionId;
        if (section) {
          useWorkspaceStore.getState().triggerRefresh(section);
        }
      } else if (action.action === "switch_tab") {
        const tab = action.value as SectionId;
        if (tab) {
          useWorkspaceStore.getState().setActiveSection(tab);
        }
      }
    },
    [applyPreset, toggleLayoutSection],
  );

  // Register action handler with chat store
  useEffect(() => {
    useChatStore.getState().setOnAction(handleAction);
  }, [handleAction]);

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

  // AI proactive greeting — dynamic, context-aware (LOOM + LECTOR state)
  useEffect(() => {
    if (!course) return;
    const greetingKey = `greeting_shown_${courseId}`;
    if (sessionStorage.getItem(greetingKey) === "true") return;

    const chatState = useChatStore.getState();
    const existing = chatState.messagesByCourse[courseId];
    if (existing && existing.length > 0) return;

    sessionStorage.setItem(greetingKey, "true");

    // Fetch dynamic greeting from backend (uses LOOM mastery + LECTOR review state)
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
              messagesByCourse: {
                ...s.messagesByCourse,
                [courseId]: [greetingMsg],
              },
              messages:
                s.activeCourseId === courseId ? [greetingMsg] : s.messages,
            }));
          }
        })
        .catch(() => {
          // Fallback to static welcome_message if greeting endpoint fails
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
              messagesByCourse: {
                ...s.messagesByCourse,
                [courseId]: [welcomeMsg],
              },
              messages:
                s.activeCourseId === courseId ? [welcomeMsg] : s.messages,
            }));
          }
        });
    });
  }, [course, courseId]);

  const chatVisible = layout.chat_visible;

  return (
    <div className="h-screen flex flex-col bg-background">
      <WorkspaceHeader courseName={course?.name || "Course"} courseId={courseId} />
      <div className="px-3 pt-3 space-y-2">
        <RuntimeAlert health={health} />
        <IngestionProgress courseId={courseId} />
      </div>
      <AppShell
        courseId={courseId}
        tree={layout.tree_visible ? <CourseTree courseId={courseId} /> : undefined}
        chat={chatVisible ? <ChatView courseId={courseId} aiActionsEnabled={aiActionsEnabled} /> : undefined}
      >
        <SectionContainer
          courseId={courseId}
          reviewEnabled={true}
          aiActionsEnabled={aiActionsEnabled}
          visibleSections={visibleSections}
        />
      </AppShell>
    </div>
  );
}
