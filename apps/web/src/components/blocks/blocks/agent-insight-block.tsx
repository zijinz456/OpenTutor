"use client";

import { Sparkles, ArrowRight, GraduationCap, Compass, Clock, Shield } from "lucide-react";
import { useRouter } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import type { BlockComponentProps } from "@/lib/block-system/registry";
import type { LearningMode } from "@/lib/block-system/types";
import { useT } from "@/lib/i18n-context";

const MODE_ICONS: Record<string, typeof GraduationCap> = {
  course_following: GraduationCap,
  self_paced: Compass,
  exam_prep: Clock,
  maintenance: Shield,
};

export default function AgentInsightBlock({ courseId, blockId, config }: BlockComponentProps) {
  const router = useRouter();
  const t = useT();
  const setLearningMode = useWorkspaceStore((s) => s.setLearningMode);
  const dismissAgentBlock = useWorkspaceStore((s) => s.dismissAgentBlock);
  const insightType = config.insightType as string | undefined;
  const suggestedMode = config.suggestedMode as LearningMode | undefined;
  const reason = config.reason as string | undefined;

  const handleCta = () => {
    if (insightType === "review_needed") {
      router.push(`/course/${courseId}/review`);
    } else if (insightType === "mode_suggestion" && suggestedMode) {
      setLearningMode(suggestedMode);
      dismissAgentBlock(blockId);
    }
  };

  const ModeIcon = suggestedMode ? MODE_ICONS[suggestedMode] : null;

  return (
    <div className="flex items-center gap-4 p-4">
      <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-brand-muted shrink-0">
        {insightType === "mode_suggestion" && ModeIcon ? (
          <ModeIcon className="size-5 text-brand" />
        ) : (
          <Sparkles className="size-5 text-brand" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        {insightType === "review_needed" && (
          <>
            <p className="text-sm font-medium text-foreground">Time to review</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Some concepts are at risk of fading. A quick review will help retain them.
            </p>
          </>
        )}
        {insightType === "mode_suggestion" && suggestedMode && (
          <>
            <p className="text-sm font-medium text-foreground">
              {t("mode.switch")}: {t(`mode.${suggestedMode}`)}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {reason || t(`mode.${suggestedMode}.desc`)}
            </p>
          </>
        )}
        {!insightType && (
          <p className="text-sm text-muted-foreground">Your AI tutor has a suggestion.</p>
        )}
      </div>

      {insightType === "review_needed" && (
        <button
          onClick={handleCta}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-brand-foreground bg-brand rounded-lg hover:opacity-90 transition-opacity shrink-0"
        >
          Start Review
          <ArrowRight className="size-3.5" />
        </button>
      )}

      {insightType === "mode_suggestion" && suggestedMode && (
        <button
          onClick={handleCta}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-brand-foreground bg-brand rounded-lg hover:opacity-90 transition-opacity shrink-0"
        >
          {t("mode.switch")}
          <ArrowRight className="size-3.5" />
        </button>
      )}
    </div>
  );
}
