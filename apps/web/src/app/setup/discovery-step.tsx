"use client";

import type { ParseStep } from "../new/types";

interface DiscoveryStepProps {
  parseSteps: ParseStep[];
  parseProgress: number;
  parseLogs: { text: string; color: string }[];
  hasCompletedJob: boolean;
  allJobsFailed: boolean;
  noSourcesSubmitted: boolean;
  aiProbeResponse: string;
  aiProbeStreaming: boolean;
  aiProbeDone: boolean;
  canEnterEarly: boolean;
  onEnterWorkspace: () => void;
  t: (key: string) => string;
}

export function DiscoveryStep({
  parseSteps, parseProgress, parseLogs,
  hasCompletedJob, allJobsFailed, noSourcesSubmitted,
  aiProbeResponse, aiProbeStreaming, aiProbeDone,
  canEnterEarly, onEnterWorkspace, t,
}: DiscoveryStepProps) {
  const showProbe = hasCompletedJob || noSourcesSubmitted;
  const canEnter = canEnterEarly || aiProbeDone || allJobsFailed || noSourcesSubmitted;

  return (
    <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-3 duration-300">
      <div>
        <h3 className="text-lg font-semibold text-foreground">{t("setup.discovering")}</h3>
        <p className="text-sm text-muted-foreground mt-1">{t("setup.discoveringDesc")}</p>
      </div>

      {/* Ingestion progress */}
      <div className="flex flex-col gap-3">
        {/* Progress bar */}
        <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-brand rounded-full transition-all duration-500"
            style={{ width: `${parseProgress}%` }}
          />
        </div>

        {/* Parse steps */}
        <div className="flex gap-2 flex-wrap">
          {parseSteps.map((ps, i) => (
            <span
              key={i}
              className={`text-xs px-2 py-0.5 rounded-full ${
                ps.status === "done"
                  ? "bg-success-muted text-success"
                  : ps.status === "active"
                    ? "bg-brand-muted text-brand"
                    : "bg-muted text-muted-foreground"
              }`}
            >
              {ps.label}
            </span>
          ))}
        </div>

        {/* Logs */}
        {parseLogs.length > 0 && (
          <div className="max-h-24 overflow-y-auto bg-muted rounded-lg p-2 space-y-0.5">
            {parseLogs.slice(-8).map((log, i) => (
              <p key={i} className={`text-xs font-mono ${log.color}`}>{log.text}</p>
            ))}
          </div>
        )}
      </div>

      {/* AI Probe */}
      {showProbe && (
        <div className="flex flex-col gap-3 border-t border-border pt-4">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${aiProbeStreaming ? "bg-brand animate-pulse" : aiProbeDone ? "bg-success" : "bg-muted-foreground"}`} />
            <span className="text-sm font-medium text-foreground">
              {aiProbeStreaming ? t("setup.analyzing") : aiProbeDone ? t("setup.analysisComplete") : t("setup.waitingForAnalysis")}
            </span>
          </div>

          {aiProbeResponse && (
            <div className="bg-card border border-border rounded-lg p-4 max-h-64 overflow-y-auto">
              <div className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                {aiProbeResponse}
                {aiProbeStreaming && <span className="inline-block w-1.5 h-4 bg-brand animate-pulse ml-0.5 align-text-bottom" />}
              </div>
            </div>
          )}

          {!aiProbeResponse && aiProbeStreaming && (
            <div className="flex items-center gap-3 py-4">
              <div className="w-6 h-6 border-2 border-brand border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-muted-foreground">{t("setup.analyzing")}</span>
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {allJobsFailed && !noSourcesSubmitted && (
        <div className="p-3 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive">
          {t("setup.ingestionFailed")}
        </div>
      )}

      {/* Enter workspace */}
      <button
        onClick={onEnterWorkspace}
        disabled={!canEnter}
        data-testid="setup-enter-workspace"
        className={`h-11 px-8 rounded-lg text-sm font-semibold self-start ${
          canEnter
            ? "bg-brand text-brand-foreground hover:opacity-90"
            : "bg-brand/40 text-brand-foreground/60 cursor-not-allowed"
        }`}
      >
        {t("setup.enterWorkspace")}
      </button>
    </div>
  );
}
