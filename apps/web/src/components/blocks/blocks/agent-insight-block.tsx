"use client";

import { useEffect, useRef } from "react";
import { Sparkles, ArrowRight, GraduationCap, Compass, Clock, Shield, AlertTriangle, Flame, LayoutGrid } from "lucide-react";
import { useRouter } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import type { BlockType, LearningMode } from "@/lib/block-system/types";
import { useT } from "@/lib/i18n-context";

const MODE_ICONS: Record<string, typeof GraduationCap> = {
  course_following: GraduationCap,
  self_paced: Compass,
  exam_prep: Clock,
  maintenance: Shield,
};

const INSIGHT_CONFIG: Record<string, {
  icon: typeof Sparkles;
  title: string;
  desc: string;
  cta?: string;
  autoDismissMs?: number;
}> = {
  review_needed: {
    icon: Sparkles,
    title: "Time to review",
    desc: "Some concepts are at risk of fading. A quick review will help retain them.",
    cta: "Start Review",
  },
  weak_topic: {
    icon: AlertTriangle,
    title: "Weak spot detected",
    desc: "You may benefit from extra practice on this topic.",
    cta: "Add Quiz",
  },
  streak_milestone: {
    icon: Flame,
    title: "Study streak!",
    desc: "Keep up the great work!",
    autoDismissMs: 10_000,
  },
  layout_suggestion: {
    icon: LayoutGrid,
    title: "Layout suggestion",
    desc: "Your AI tutor thinks a different template might work better.",
    cta: "Apply Template",
  },
  feature_unlock: {
    icon: Sparkles,
    title: "New feature unlocked",
    desc: "",  // Will use reason from config
    cta: "Add to workspace",
  },
};

export default function AgentInsightBlock({ courseId, blockId, config }: BlockComponentProps) {
  const router = useRouter();
  const t = useT();
  const setLearningMode = useWorkspaceStore((s) => s.setLearningMode);
  const dismissAgentBlock = useWorkspaceStore((s) => s.dismissAgentBlock);
  const addBlock = useWorkspaceStore((s) => s.addBlock);
  const applyBlockTemplate = useWorkspaceStore((s) => s.applyBlockTemplate);
  const insightType = config.insightType as string | undefined;
  const suggestedMode = config.suggestedMode as LearningMode | undefined;
  const reason = config.reason as string | undefined;
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
    if (insightType === "review_needed") {
      router.push(`/course/${courseId}/review`);
    } else if (insightType === "mode_suggestion" && suggestedMode) {
      setLearningMode(suggestedMode);
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
        addBlock(blockType as BlockType, {}, "user");
        dismissAgentBlock(blockId);
      }
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
    : insightCfg?.title ?? "Your AI tutor has a suggestion.";
  const desc = insightType === "mode_suggestion"
    ? reason || (suggestedMode ? t(`mode.${suggestedMode}.desc`) : "")
    : reason || (insightType === "weak_topic" && topicName
        ? `You're struggling with "${topicName}". Want a focused quiz?`
        : insightCfg?.desc ?? "");
  const ctaLabel = insightType === "mode_suggestion"
    ? t("mode.switch")
    : insightCfg?.cta;

  return (
    <div className="flex items-center gap-4 p-4">
      <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-brand-muted shrink-0">
        <ModeIcon className="size-5 text-brand" />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {desc && (
          <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
        )}
      </div>

      {ctaLabel && (
        <button
          onClick={handleCta}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-brand-foreground bg-brand rounded-lg hover:opacity-90 transition-opacity shrink-0"
        >
          {ctaLabel}
          <ArrowRight className="size-3.5" />
        </button>
      )}
    </div>
  );
}
