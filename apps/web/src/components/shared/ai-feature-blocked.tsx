"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n-context";

interface AiFeatureBlockedProps {
  className?: string;
  compact?: boolean;
}

export function AiFeatureBlocked({
  className,
  compact = false,
}: AiFeatureBlockedProps) {
  const router = useRouter();
  const t = useT();

  return (
    <div
      role="alert"
      className={cn(
        "rounded-2xl border border-amber-300/60 bg-amber-50/80 text-amber-950 card-shadow",
        compact ? "px-3 py-2" : "px-4 py-3",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className={cn("font-medium", compact ? "text-xs" : "text-sm")}>
          {t("featureGate.llmTitle")}
        </p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 border-amber-300 bg-transparent px-2 text-xs text-amber-950 hover:bg-amber-100"
          onClick={() => router.push("/settings")}
        >
          {t("featureGate.openSettings")}
        </Button>
      </div>
      <p className={cn("mt-1 text-amber-900/85", compact ? "text-xs" : "text-sm")}>
        {t("featureGate.llmBody")}
      </p>
    </div>
  );
}
