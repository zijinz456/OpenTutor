"use client";

import { useEffect, useRef } from "react";
import { Sparkles, ArrowRight, GraduationCap, Compass, Clock, Shield, AlertTriangle, Flame, LayoutGrid, Brain, BookOpen, HandMetal } from "lucide-react";
import { useRouter } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import type { BlockType, LearningMode } from "@/lib/block-system/types";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { logAgentDecision } from "@/lib/api";
import { useT } from "@/lib/i18n-context";

const MODE_ICONS: Record<string, typeof GraduationCap> = {
  course_following: GraduationCap,
  self_paced: Compass,
  exam_prep: Clock,
  maintenance: Shield,
};

const INSIGHT_CONFIG: Record<string, {
  icon: typeof Sparkles;
  titleKey: string;
  descKey: string;
  ctaKey?: string;
  autoDismissMs?: number;
}> = {
  review_needed: {
    icon: Sparkles,
    titleKey: "insight.reviewNeeded.title",
    descKey: "insight.reviewNeeded.desc",
    ctaKey: "insight.reviewNeeded.cta",
  },
  weak_topic: {
    icon: AlertTriangle,
    titleKey: "insight.weakTopic.title",
    descKey: "insight.weakTopic.desc",
    ctaKey: "insight.weakTopic.cta",
  },
  streak_milestone: {
    icon: Flame,
    titleKey: "insight.streak.title",
    descKey: "insight.streak.desc",
    autoDismissMs: 10_000,
  },
  layout_suggestion: {
    icon: LayoutGrid,
    titleKey: "insight.layout.title",
    descKey: "insight.layout.desc",
    ctaKey: "insight.layout.cta",
  },
  feature_unlock: {
    icon: Sparkles,
    titleKey: "insight.featureUnlock.title",
    descKey: "",  // Will use reason from config
    ctaKey: "insight.featureUnlock.cta",
  },
  cognitive_alert: {
    icon: Brain,
    titleKey: "insight.cognitiveAlert.title",
    descKey: "insight.cognitiveAlert.desc",
    ctaKey: "insight.cognitiveAlert.cta",
  },
  weak_topic_focus: {
    icon: BookOpen,
    titleKey: "insight.weakTopicFocus.title",
    descKey: "insight.weakTopicFocus.desc",
    ctaKey: "insight.weakTopicFocus.cta",
  },
  welcome_back: {
    icon: HandMetal,
    titleKey: "insight.welcomeBack.title",
    descKey: "insight.welcomeBack.desc",
    ctaKey: "insight.welcomeBack.cta",
    autoDismissMs: 15_000,
  },
};

export default function AgentInsightBlock({ courseId, blockId, config }: BlockComponentProps) {
  const router = useRouter();
  const t = useT();
  const setLearningMode = useWorkspaceStore((s) => s.setLearningMode);
  const dismissAgentBlock = useWorkspaceStore((s) => s.dismissAgentBlock);
  const addBlock = useWorkspaceStore((s) => s.addBlock);
  const applyBlockTemplate = useWorkspaceStore((s) => s.applyBlockTemplate);
  const block = useWorkspaceStore((s) => s.spaceLayout.blocks.find((b) => b.id === blockId));
  const needsApproval = !!block?.agentMeta?.needsApproval;
  const insightType = config.insightType as string | undefined;
  const suggestedMode = config.suggestedMode as LearningMode | undefined;
  const reason = config.reason as string | undefined;
  const suggestionSignals = Array.isArray(config.suggestionSignals)
    ? config.suggestionSignals.filter((s): s is string => typeof s === "string")
    : [];
  const suggestedTemplate = config.suggestedTemplate as string | undefined;
  const topicName = config.topicName as string | undefined;

  // Auto-dismiss for transient insights
  const autoDismissMs = insightType ? INSIGHT_CONFIG[insightType]?.autoDismissMs : undefined;
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (!autoDismissMs) return;
    dismissTimerRef.current = setTimeout(() => dismissAgentBlock(blockId), autoDismissMs);
    return () => clearTimeout(dismissTimerRef.current);
  }, [autoDismissMs, blockId, dismissAgentBlock]);

  const handleCta = () => {
    if (needsApproval) return;
    if (insightType === "review_needed") {
      router.push(`/course/${courseId}/review`);
    } else if (insightType === "mode_suggestion" && suggestedMode) {
      void logAgentDecision({
        course_id: courseId,
        action: "apply_mode_suggestion_direct",
        title: t("mode.switch"),
        reason,
        decision_type: "mode_suggestion",
        source: "agent_insight_block",
        top_signal_type: "manual_override",
        metadata_json: {
          suggested_mode: suggestedMode,
          signals: suggestionSignals,
        },
      }).catch(() => undefined);
      setLearningMode(suggestedMode);
      updateUnlockContext(courseId, { mode: suggestedMode });
      dismissAgentBlock(blockId);
    } else if (insightType === "weak_topic") {
      addBlock("quiz", topicName ? { topic: topicName } : {}, "agent");
      dismissAgentBlock(blockId);
    } else if (insightType === "layout_suggestion" && suggestedTemplate) {
      applyBlockTemplate(suggestedTemplate);
      dismissAgentBlock(blockId);
    } else if (insightType === "feature_unlock") {
      const blockType = config.suggestedBlockType as string | undefined;
      if (blockType) {
        addBlock(blockType as BlockType, {}, "agent");
        dismissAgentBlock(blockId);
      }
    } else if (insightType === "cognitive_alert") {
      // Undo the layout simplification
      const undoLayout = useWorkspaceStore.getState().undoLayout;
      undoLayout();
      dismissAgentBlock(blockId);
    } else if (insightType === "weak_topic_focus") {
      // Add a review block targeting the weak topics
      addBlock("review", { topics: config.weakTopics ?? [] }, "agent");
      dismissAgentBlock(blockId);
    } else if (insightType === "welcome_back") {
      // Navigate to review
      addBlock("review", {}, "agent");
      dismissAgentBlock(blockId);
    }
  };

  // Determine icon
  const ModeIcon = insightType === "mode_suggestion" && suggestedMode
    ? MODE_ICONS[suggestedMode] ?? Sparkles
    : insightType && INSIGHT_CONFIG[insightType]
      ? INSIGHT_CONFIG[insightType].icon
      : Sparkles;

  // Determine text
  const insightCfg = insightType ? INSIGHT_CONFIG[insightType] : undefined;
  const title = insightType === "mode_suggestion" && suggestedMode
    ? `${t("mode.switch")}: ${t(`mode.${suggestedMode}`)}`
    : insightCfg?.titleKey
      ? t(insightCfg.titleKey)
      : t("insight.defaultTitle");
  const desc = insightType === "mode_suggestion"
    ? reason || (suggestedMode ? t(`mode.${suggestedMode}.desc`) : "")
    : reason || (insightType === "weak_topic" && topicName
        ? t("insight.weakTopic.topicDesc").replace("{topic}", topicName)
        : insightCfg?.descKey
          ? t(insightCfg.descKey)
          : "");
  const ctaLabel = insightType === "mode_suggestion"
    ? t("mode.switch")
    : insightCfg?.ctaKey
      ? t(insightCfg.ctaKey)
      : undefined;

  return (
    <div role="alert" aria-label={title} className="flex items-center gap-4 p-4 bg-brand-muted/20 rounded-2xl">
      <div className="flex items-center justify-center w-10 h-10 rounded-2xl bg-brand-muted shrink-0">
        <ModeIcon className="size-5 text-brand" aria-hidden="true" />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {desc && (
          <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
        )}
        {insightType === "mode_suggestion" && suggestionSignals.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {suggestionSignals.map((signal) => (
              <span
                key={signal}
                className="inline-flex rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
              >
                {signal}
              </span>
            ))}
          </div>
        ) : null}
        {insightType === "cognitive_alert" && Array.isArray(config.hiddenBlocks) && config.hiddenBlocks.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {(config.hiddenBlocks as string[]).map((bt) => (
              <span key={bt} className="inline-flex rounded-full bg-red-100 dark:bg-red-900/30 px-2 py-0.5 text-[10px] text-red-700 dark:text-red-400">
                {bt}
              </span>
            ))}
          </div>
        )}
        {insightType === "weak_topic_focus" && Array.isArray(config.weakTopics) && config.weakTopics.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {(config.weakTopics as string[]).map((topic) => (
              <span key={topic} className="inline-flex rounded-full bg-yellow-100 dark:bg-yellow-900/30 px-2 py-0.5 text-[10px] text-yellow-700 dark:text-yellow-400">
                {topic}
              </span>
            ))}
          </div>
        )}
      </div>

      {ctaLabel && !needsApproval && (
        <button
          onClick={handleCta}
          aria-label={ctaLabel}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-brand-foreground bg-brand rounded-xl hover:opacity-90 transition-opacity shrink-0"
        >
          {ctaLabel}
          <ArrowRight className="size-3.5" />
        </button>
      )}
    </div>
  );
}
