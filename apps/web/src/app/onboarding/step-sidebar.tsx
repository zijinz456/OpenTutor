import { useT } from "@/lib/i18n-context";
import type { OnboardingStep } from "./types";

interface StepSidebarProps {
  steps: OnboardingStep[];
  currentStep: number;
  onStepClick: (index: number) => void;
}

const SIDEBAR_LABELS: Record<string, string> = {
  language: "pref.language",
  learning_mode: "onboarding.sidebar.learningMode",
  detail_level: "onboarding.sidebar.outputFormat",
  layout_preset: "onboarding.sidebar.layoutTemplate",
  example_style: "onboarding.sidebar.finish",
};

export function StepSidebar({ steps, currentStep, onStepClick }: StepSidebarProps) {
  const t = useT();

  return (
    <aside className="w-[280px] p-6 flex flex-col gap-5 shrink-0">
      <div className="flex items-center gap-2.5 px-2">
        <span className="text-sidebar-foreground font-bold text-lg">
          OpenTutor
        </span>
      </div>

      <nav className="flex flex-col gap-1">
        {steps.map((candidate, index) => {
          const isDone = index < currentStep;
          const isCurrent = index === currentStep;
          const canClick = index <= currentStep;

          let stepIndicatorClass: string;
          if (isDone) {
            stepIndicatorClass = "bg-success text-success-foreground";
          } else if (isCurrent) {
            stepIndicatorClass = "bg-sidebar-foreground text-sidebar";
          } else {
            stepIndicatorClass = "border border-sidebar-border text-sidebar-foreground/50";
          }

          let labelClass: string;
          if (isDone) {
            labelClass = "text-sidebar-foreground/60 font-medium";
          } else if (isCurrent) {
            labelClass = "text-sidebar-foreground font-semibold";
          } else {
            labelClass = "text-sidebar-foreground/40";
          }

          return (
            <button
              type="button"
              key={candidate.dimension}
              onClick={() => canClick && onStepClick(index)}
              className={`flex items-center gap-2.5 h-10 px-3 rounded-md transition-colors ${
                isCurrent ? "bg-sidebar-accent" : isDone ? "bg-sidebar-accent/60" : ""
              } ${canClick ? "cursor-pointer" : "cursor-default"}`}
            >
              <div
                className={`w-[22px] h-[22px] rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${stepIndicatorClass}`}
              >
                {isDone ? "\u2713" : index + 1}
              </div>
              <span className={`text-[13px] ${labelClass}`}>
                {t(SIDEBAR_LABELS[candidate.dimension] ?? candidate.dimension)}
              </span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
