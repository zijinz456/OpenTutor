"use client";

import type { FileItem, ParseStep, ParseLog } from "./types";
import { StepIndicator } from "./step-indicator";

interface ParsingProgressStepProps {
  projectName: string;
  url: string;
  files: FileItem[];
  parseSteps: ParseStep[];
  parseProgress: number;
  parseLogs: ParseLog[];
  canContinueToFeatures: boolean;
  allJobsFailed: boolean;
  createdCourseId: string | null;
  onEnterWorkspace: () => void;
  onContinueToFeatures: () => void;
  t: (key: string) => string;
}

export function ParsingProgressStep({
  projectName,
  url,
  files,
  parseSteps,
  parseProgress,
  parseLogs,
  canContinueToFeatures,
  allJobsFailed,
  createdCourseId,
  onEnterWorkspace,
  onContinueToFeatures,
  t,
}: ParsingProgressStepProps) {
  return (
    <div className="h-screen flex flex-col animate-in fade-in duration-300">
      {/* Top bar */}
      <div className="h-12 px-6 bg-muted border-b border-border flex items-center gap-4 shrink-0">
        <span className="font-semibold text-sm text-foreground">
          {t("new.processingPrefix")} -- {projectName || t("new.newProject")}
        </span>
        <div className="flex-1" />
        <StepIndicator currentStep="parsing" t={t} />
        <StatusBadge allJobsFailed={allJobsFailed} t={t} />
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Main content (left) */}
        <MainContent
          url={url}
          files={files}
          canContinueToFeatures={canContinueToFeatures}
          allJobsFailed={allJobsFailed}
          t={t}
        />

        {/* Parsing Sidebar (right) */}
        <ParsingSidebar
          projectName={projectName}
          url={url}
          files={files}
          parseSteps={parseSteps}
          parseProgress={parseProgress}
          parseLogs={parseLogs}
          canContinueToFeatures={canContinueToFeatures}
          createdCourseId={createdCourseId}
          onEnterWorkspace={onEnterWorkspace}
          onContinueToFeatures={onContinueToFeatures}
          t={t}
        />
      </div>
    </div>
  );
}

/* ---------- Sub-components ---------- */

function StatusBadge({ allJobsFailed, t }: { allJobsFailed: boolean; t: (key: string) => string }) {
  return (
    <div className={`flex items-center gap-1.5 px-2.5 h-6 rounded ${allJobsFailed ? "bg-destructive/10" : "bg-success-muted"}`}>
      <div className={`w-1.5 h-1.5 rounded-full ${allJobsFailed ? "bg-destructive" : "bg-success"}`} />
      <span className={`text-[11px] font-semibold ${allJobsFailed ? "text-destructive" : "text-success"}`}>
        {allJobsFailed ? t("new.needsAttention") : t("new.active")}
      </span>
    </div>
  );
}

interface MainContentProps {
  url: string;
  files: FileItem[];
  canContinueToFeatures: boolean;
  allJobsFailed: boolean;
  t: (key: string) => string;
}

function MainContent({ url, files, canContinueToFeatures, allJobsFailed, t }: MainContentProps) {
  return (
    <div className="flex-1 flex flex-col bg-background">
      {url && (
        <div className="h-9 px-4 bg-muted border-b border-border flex items-center gap-2">
          <span className="text-xs text-muted-foreground flex-1 truncate">{url}</span>
          {!canContinueToFeatures && <span className="text-xs text-muted-foreground animate-pulse">{t("new.loading")}</span>}
        </div>
      )}
      <div className="flex-1 p-6 bg-muted/50 flex flex-col gap-4 overflow-y-auto">
        <h2 className="text-xl font-bold text-foreground">{t("new.processingTitle")}</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {t("new.processingDesc")}
        </p>
        {files.length > 0 && (
          <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
            {t("new.processingFiles")} {files.length} {t(files.length === 1 ? "new.fileCountOne" : "new.fileCountMany")}: {files.map((f) => f.name).join(", ")}
          </div>
        )}
        {allJobsFailed && (
          <div className="p-3 px-4 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive leading-relaxed">
            {t("new.allJobsFailed")}
          </div>
        )}
      </div>
    </div>
  );
}

interface ParsingSidebarProps {
  projectName: string;
  url: string;
  files: FileItem[];
  parseSteps: ParseStep[];
  parseProgress: number;
  parseLogs: ParseLog[];
  canContinueToFeatures: boolean;
  createdCourseId: string | null;
  onEnterWorkspace: () => void;
  onContinueToFeatures: () => void;
  t: (key: string) => string;
}

function ParsingSidebar({
  projectName,
  url,
  files,
  parseSteps,
  parseProgress,
  parseLogs,
  canContinueToFeatures,
  createdCourseId,
  onEnterWorkspace,
  onContinueToFeatures,
  t,
}: ParsingSidebarProps) {
  return (
    <div className="w-[340px] border-l border-border bg-background flex flex-col shrink-0">
      <div className="h-11 px-4 bg-muted border-b border-border flex items-center gap-2 shrink-0">
        {!canContinueToFeatures && <span className="text-xs text-brand animate-pulse">...</span>}
        <span className="font-semibold text-[13px] text-foreground">{t("new.parsingProgress")}</span>
      </div>
      <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto">
        <div className="flex flex-col gap-1.5">
          <span className="font-semibold text-sm text-foreground">
            {projectName || t("new.newProject")}
          </span>
          <span className="text-xs text-muted-foreground">
            {files.length} {t(files.length === 1 ? "new.fileCountOne" : "new.fileCountMany")}{url ? ` + 1 ${t("new.urlSourceOne")}` : ""}
          </span>
        </div>

        {/* Progress bar */}
        <div className="flex flex-col gap-1.5">
          <div className="w-full h-1.5 bg-muted rounded-full">
            <div
              className="h-1.5 bg-brand rounded-full transition-all duration-500"
              style={{ width: `${parseProgress}%` }}
            />
          </div>
          <span className="text-xs font-medium text-brand">{parseProgress}% {t("new.completeSuffix")}</span>
        </div>

        {/* Steps */}
        <div className="flex flex-col gap-3">
          {parseSteps.map((ps, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <StepDot status={ps.status} />
              <span
                className={`text-xs ${
                  ps.status === "done"
                    ? "text-foreground font-medium"
                    : ps.status === "active"
                    ? "text-brand font-semibold"
                    : "text-muted-foreground"
                }`}
              >
                {ps.label}
              </span>
            </div>
          ))}
        </div>

        <div className="w-full h-px bg-border" />

        {/* Processing Log */}
        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-muted-foreground">{t("new.processingLog")}</span>
          {parseLogs.map((log, idx) => (
            <span key={idx} className={`text-[11px] font-mono ${log.color}`}>
              {log.text}
            </span>
          ))}
        </div>

        <div className="flex-1" />

        <div className="flex flex-col gap-2">
          {createdCourseId && (
            <button
              type="button"
              onClick={onEnterWorkspace}
              data-testid="enter-now"
              className="w-full h-11 border border-border text-foreground rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:border-foreground/20"
            >
              {t("new.enterNow")}
            </button>
          )}
          {canContinueToFeatures && (
            <button
              type="button"
              onClick={onContinueToFeatures}
              data-testid="continue-to-features"
              className="w-full h-11 bg-brand text-brand-foreground rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:opacity-90"
            >
              {t("new.continueToFeatures")} &rarr;
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function StepDot({ status }: { status: ParseStep["status"] }) {
  let dotClass = "border border-border";
  if (status === "done") {
    dotClass = "bg-success";
  } else if (status === "active") {
    dotClass = "bg-brand";
  }

  return (
    <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${dotClass}`}>
      {status === "done" && <span className="text-[10px] text-success-foreground font-bold">{"\u2713"}</span>}
      {status === "active" && <span className="text-[10px] text-brand-foreground animate-pulse font-bold">...</span>}
    </div>
  );
}
