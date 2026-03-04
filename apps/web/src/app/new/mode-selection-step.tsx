"use client";

import type { Mode } from "./types";
import { StepIndicator } from "./step-indicator";

interface ModeSelectionStepProps {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onContinue: () => void;
  onBack: () => void;
  t: (key: string) => string;
}

const MODE_OPTIONS: { key: Mode; labelKey: string; descKey: string }[] = [
  { key: "upload", labelKey: "new.mode.upload", descKey: "new.mode.uploadDesc" },
  { key: "url", labelKey: "new.mode.url", descKey: "new.mode.urlDesc" },
  { key: "both", labelKey: "new.mode.both", descKey: "new.mode.bothDesc" },
];

export function ModeSelectionStep({
  mode,
  onModeChange,
  onContinue,
  onBack,
  t,
}: ModeSelectionStepProps) {
  return (
    <div className="h-screen flex items-center justify-center">
      <div className="w-[640px] flex flex-col gap-10 items-center animate-in fade-in duration-300">
        <div className="flex flex-col gap-3 items-center text-center">
          <StepIndicator currentStep="mode" t={t} />
          <h1 className="text-[32px] font-bold text-foreground mt-4">
            {t("new.mode.title")}
          </h1>
          <p className="text-[15px] text-muted-foreground max-w-[480px] leading-relaxed">
            {t("new.mode.subtitle")}
          </p>
        </div>

        <div className="flex gap-4 w-full">
          {MODE_OPTIONS.map((m) => (
            <button
              type="button"
              key={m.key}
              onClick={() => onModeChange(m.key)}
              data-testid={`mode-option-${m.key}`}
              aria-pressed={mode === m.key}
              data-selected={mode === m.key ? "true" : "false"}
              className={`flex-1 flex flex-col items-center justify-center gap-3.5 p-7 rounded-[10px] transition-all ${
                mode === m.key
                  ? "border-2 border-brand bg-brand-muted"
                  : "border border-border hover:border-foreground/20"
              }`}
            >
              <span className="font-semibold text-base text-foreground">
                {t(m.labelKey)}
              </span>
              <span className="text-[13px] text-muted-foreground text-center leading-snug">
                {t(m.descKey)}
              </span>
            </button>
          ))}
        </div>

        <div className="flex justify-between w-full mt-2">
          <button
            type="button"
            data-testid="back-to-projects"
            onClick={onBack}
            className="h-11 px-6 border border-border rounded-lg flex items-center gap-1.5 text-muted-foreground font-medium text-sm hover:border-foreground/20"
          >
            &larr; {t("new.backToProjects")}
          </button>
          <button
            type="button"
            onClick={onContinue}
            data-testid="mode-continue"
            className="h-11 px-7 bg-brand text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm hover:opacity-90"
          >
            {t("new.continue")} &rarr;
          </button>
        </div>
      </div>
    </div>
  );
}
