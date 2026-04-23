"use client";

/**
 * Phase 7 guardrails — session-level strict-mode toggle.
 *
 * Pill-style toggle that lives in the chat header:
 *   OFF → neutral gray "Strict off" — tutor behaves as today.
 *   ON  → green "Strict" pill — every `POST /chat` carries
 *         `guardrails_strict: true`, forcing the tutor to ground answers in
 *         retrieved course-corpus chunks (or refuse if none match).
 *
 * State persists in `localStorage` via the chat store (see
 * `setStrictMode`); per-tab, not per-user, matching the Phase 7 flag-4
 * decision. Toggling mid-conversation is non-retroactive.
 */
import { Shield, ShieldCheck } from "lucide-react";
import { useChatStore } from "@/store/chat";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function StrictModeToggle() {
  const strictMode = useChatStore((s) => s.strictMode);
  const setStrictMode = useChatStore((s) => s.setStrictMode);

  const label = strictMode ? "Strict" : "Strict off";
  const tooltip = strictMode
    ? "Strict mode ON. Answers must be grounded in your course materials — tutor will refuse rather than guess."
    : "Strict mode OFF. Turn on to force the tutor to cite your course materials (or refuse) instead of free-styling.";

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            role="switch"
            aria-checked={strictMode}
            aria-label="Toggle strict grounded mode"
            data-testid="strict-mode-toggle"
            data-state={strictMode ? "on" : "off"}
            onClick={() => setStrictMode(!strictMode)}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-[11px] font-medium transition-colors",
              strictMode
                ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-700 hover:bg-emerald-500/25 dark:text-emerald-300"
                : "border-border/60 bg-transparent text-muted-foreground hover:bg-muted/50",
            )}
          >
            {strictMode ? (
              <ShieldCheck className="size-3.5" aria-hidden />
            ) : (
              <Shield className="size-3.5" aria-hidden />
            )}
            <span>{label}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
