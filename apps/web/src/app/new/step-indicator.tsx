"use client";

import type { Step } from "./types";
import { STEP_LABELS } from "./types";

interface StepIndicatorProps {
  currentStep: Step;
  t: (key: string) => string;
}

export function StepIndicator({ currentStep, t }: StepIndicatorProps) {
  const currentIndex = STEP_LABELS.findIndex((s) => s.key === currentStep);
  return (
    <div className="flex items-center gap-2 text-xs">
      {STEP_LABELS.map((s, i) => {
        let colorClass = "text-muted-foreground";
        if (i < currentIndex) {
          colorClass = "text-brand font-medium";
        } else if (i === currentIndex) {
          colorClass = "text-foreground font-semibold";
        }

        return (
          <span key={s.key} className="flex items-center gap-2">
            {i > 0 && <span className="text-muted-foreground">/</span>}
            <span className={colorClass}>
              {i + 1}. {t(s.labelKey)}
            </span>
          </span>
        );
      })}
    </div>
  );
}
