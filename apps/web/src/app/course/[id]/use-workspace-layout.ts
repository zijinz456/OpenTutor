import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useGroupRef } from "react-resizable-panels";
import {
  LAYOUT_PRESETS,
  type LayoutPreset,
  type RightTab,
  type HiddenPanelId,
  isRightTab,
  getActivityItemForRightTab,
} from "./workspace-types";
import type { ChatAction, CourseWorkspaceFeatures, SwitchResult } from "@/lib/api";
import { useSceneStore } from "@/store/scene";
import { useChatStore } from "@/store/chat";
import { getDefaultActivityItem, isRightTabEnabled } from "@/lib/course-config";

function getPreferredPracticeTab(features: CourseWorkspaceFeatures): RightTab {
  if (features.practice) return "quiz";
  if (features.wrong_answer) return "review";
  if (features.study_plan) return "plan";
  return "progress";
}

function getFallbackRightTab(features: CourseWorkspaceFeatures): RightTab {
  const preferred = getPreferredPracticeTab(features);
  if (isRightTabEnabled(preferred, features)) {
    return preferred;
  }
  return "progress";
}

function isPracticeAreaEnabled(features: CourseWorkspaceFeatures): boolean {
  return features.practice || features.wrong_answer || features.study_plan;
}

export function useWorkspaceLayout(courseId: string, features: CourseWorkspaceFeatures) {
  const panelGroupRef = useGroupRef();
  const initialSceneAppliedRef = useRef<string | null>(null);
  const hadActiveTaskRef = useRef(false);

  const { sceneConfig, switchScene: doSwitchScene } = useSceneStore();
  const { setOnAction } = useChatStore();

  const [rightTab, setRightTab] = useState<RightTab>("quiz");
  const [activityItem, setActivityItem] = useState(getDefaultActivityItem(features));
  const [hiddenPanels, setHiddenPanels] = useState<Set<HiddenPanelId>>(new Set());
  const [layoutPreset, setLayoutPreset] = useState<LayoutPreset>("balanced");
  const [prefDialogOpen, setPrefDialogOpen] = useState(false);
  const [pendingPrefChanges, setPendingPrefChanges] = useState<Array<{ dimension: string; value: string }>>([]);

  const resolvedRightTab = useMemo(
    () => (isRightTabEnabled(rightTab, features) ? rightTab : getFallbackRightTab(features)),
    [features, rightTab],
  );
  const resolvedHiddenPanels = useMemo(() => {
    const next = new Set(hiddenPanels);
    if (!features.notes) next.add("notes");
    if (!features.free_qa) next.add("chat");
    return next;
  }, [features.free_qa, features.notes, hiddenPanels]);
  const resolvedActivityItem = useMemo(() => {
    if (activityItem === "notes" && !features.notes) return getDefaultActivityItem(features);
    if (activityItem === "chat" && !features.free_qa) return getDefaultActivityItem(features);
    if (activityItem === "practice" && !isPracticeAreaEnabled(features)) return "progress";
    return activityItem;
  }, [activityItem, features]);

  const applyPreset = useCallback((preset: LayoutPreset) => {
    panelGroupRef.current?.setLayout(LAYOUT_PRESETS[preset]);
    setLayoutPreset(preset);
  }, [panelGroupRef]);

  const buildWorkspaceState = useCallback(() => {
    const openTabs: Array<{ type: string; position: number }> = [];
    if (!resolvedHiddenPanels.has("pdf")) openTabs.push({ type: "pdf", position: openTabs.length });
    if (features.notes && !resolvedHiddenPanels.has("notes")) openTabs.push({ type: "notes", position: openTabs.length });
    if (!resolvedHiddenPanels.has("quiz")) openTabs.push({ type: resolvedRightTab, position: openTabs.length });
    if (features.free_qa && !resolvedHiddenPanels.has("chat")) openTabs.push({ type: "chat", position: openTabs.length });
    return {
      open_tabs: openTabs,
      layout_state: {
        hidden_panels: Array.from(resolvedHiddenPanels),
        right_tab: resolvedRightTab,
        activity_item: resolvedActivityItem,
        layout_preset: layoutPreset,
      },
      last_active_tab: !resolvedHiddenPanels.has("quiz") ? resolvedRightTab : resolvedActivityItem,
    };
  }, [features.free_qa, features.notes, layoutPreset, resolvedActivityItem, resolvedHiddenPanels, resolvedRightTab]);

  const applyWorkspaceLayout = useCallback((tabLayout?: Array<{ type: string; position: number }>) => {
    if (!tabLayout?.length) return;

    const visibleTypes = new Set(tabLayout.map((item) => item.type));
    const nextHidden = new Set<HiddenPanelId>(["pdf", "notes", "quiz", "chat"]);

    if (visibleTypes.has("pdf")) nextHidden.delete("pdf");
    if (features.notes && visibleTypes.has("notes")) nextHidden.delete("notes");
    if (features.free_qa && visibleTypes.has("chat")) nextHidden.delete("chat");

    const firstRightTab = tabLayout
      .map((item) => item.type)
      .find((item): item is RightTab => isRightTab(item) && isRightTabEnabled(item, features));

    if (firstRightTab) {
      nextHidden.delete("quiz");
      setRightTab(firstRightTab);
      setActivityItem(getActivityItemForRightTab(firstRightTab));
      applyPreset(firstRightTab === "plan" ? "notesFocused" : "quizFocused");
    } else if (visibleTypes.size >= 3) {
      applyPreset("balanced");
    }

    if (!features.notes) nextHidden.add("notes");
    if (!features.free_qa) nextHidden.add("chat");

    setHiddenPanels(nextHidden);
  }, [applyPreset, features]);

  const applySceneResult = useCallback((result: SwitchResult) => {
    if (result.tab_layout?.length) {
      applyWorkspaceLayout(result.tab_layout);
    } else if (result.config?.tab_preset?.length) {
      applyWorkspaceLayout(result.config.tab_preset);
    }

    for (const action of result.init_actions) {
      if (action.action === "load_wrong_answers" && features.wrong_answer) {
        setRightTab("review");
        setHiddenPanels((prev) => {
          const next = new Set(prev);
          next.delete("quiz");
          return next;
        });
      }
      if (action.action === "generate_study_plan" && features.study_plan) {
        setRightTab("plan");
        setHiddenPanels((prev) => {
          const next = new Set(prev);
          next.delete("quiz");
          return next;
        });
      }
      toast.message(action.message);
    }

    if (result.message) toast.message(result.message);
    if (result.explanation?.reason) toast.message(result.explanation.reason);
  }, [applyWorkspaceLayout, features.study_plan, features.wrong_answer]);

  const togglePanel = useCallback((panelId: HiddenPanelId) => {
    if ((panelId === "notes" && !features.notes) || (panelId === "chat" && !features.free_qa)) {
      return;
    }

    setHiddenPanels((prev) => {
      const next = new Set(prev);
      if (next.has(panelId)) next.delete(panelId);
      else next.add(panelId);
      return next;
    });
  }, [features.free_qa, features.notes]);

  const handleSceneSwitch = useCallback(async (sceneId: string) => {
    const result = await doSwitchScene(courseId, sceneId, buildWorkspaceState());
    applySceneResult(result);
  }, [applySceneResult, buildWorkspaceState, courseId, doSwitchScene]);

  const handleAction = useCallback((action: ChatAction) => {
    if (action.action === "set_layout_preset" && action.value) {
      const preset = action.value as LayoutPreset;
      if (preset in LAYOUT_PRESETS) applyPreset(preset);
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
    if (item === "notes" && !features.notes) {
      setActivityItem(getDefaultActivityItem(features));
      return;
    }
    if (item === "chat" && !features.free_qa) {
      setActivityItem(getDefaultActivityItem(features));
      return;
    }
    if (item === "practice" && !isPracticeAreaEnabled(features)) {
      setActivityItem("progress");
      setRightTab("progress");
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("quiz");
        return next;
      });
      applyPreset("quizFocused");
      return;
    }

    setActivityItem(item);

    if (item === "notes") {
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("notes");
        next.delete("quiz");
        if (features.free_qa) next.delete("chat");
        return next;
      });
      setRightTab(getFallbackRightTab(features));
      applyPreset("notesFocused");
    } else if (item === "practice") {
      setRightTab(getPreferredPracticeTab(features));
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
    } else if (item === "profile") {
      setRightTab("profile");
      setHiddenPanels((prev) => {
        const next = new Set(prev);
        next.delete("quiz");
        return next;
      });
      applyPreset("notesFocused");
    }
  }, [applyPreset, features]);

  const setActiveTaskTracked = useCallback((activeTask: { title?: string } | null) => {
    const hasActiveTask = Boolean(activeTask);
    if (hasActiveTask && !hadActiveTaskRef.current) {
      hadActiveTaskRef.current = true;
      queueMicrotask(() => {
        startTransition(() => {
          setRightTab("activity");
          setActivityItem("activity");
          setHiddenPanels((prev) => {
            const next = new Set(prev);
            next.delete("quiz");
            return next;
          });
        });
      });
    } else if (!hasActiveTask) {
      hadActiveTaskRef.current = false;
    }
  }, []);

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

  return {
    panelGroupRef,
    rightTab: resolvedRightTab,
    setRightTab,
    activityItem: resolvedActivityItem,
    hiddenPanels: resolvedHiddenPanels,
    layoutPreset,
    prefDialogOpen,
    setPrefDialogOpen,
    pendingPrefChanges,
    setPendingPrefChanges,
    applyPreset,
    buildWorkspaceState,
    applySceneResult,
    togglePanel,
    handleActivityClick,
    setActiveTaskTracked,
  };
}
