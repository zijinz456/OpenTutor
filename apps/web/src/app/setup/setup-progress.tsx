"use client";

type SetupStep = "llm" | "content" | "interview" | "template" | "discovery";

const STEPS: { id: SetupStep; labelKey: string }[] = [
  { id: "llm", labelKey: "setup.step.connect" },
  { id: "content", labelKey: "setup.step.feed" },
  { id: "interview", labelKey: "setup.step.interview" },
  { id: "template", labelKey: "setup.step.template" },
  { id: "discovery", labelKey: "setup.step.discover" },
];

const ORDER: Record<SetupStep, number> = { llm: 0, content: 1, interview: 2, template: 3, discovery: 4 };

interface SetupProgressProps {
  currentStep: SetupStep;
  t: (key: string) => string;
}

export function SetupProgress({ currentStep, t }: SetupProgressProps) {
  const currentIndex = ORDER[currentStep];

  return (
    <div className="flex items-center gap-3">
      {STEPS.map((step, i) => {
        const done = i < currentIndex;
        const active = i === currentIndex;
        return (
          <div key={step.id} className="flex items-center gap-3">
            {i > 0 && (
              <div className={`w-8 h-px ${done ? "bg-brand" : "bg-border"}`} />
            )}
            <div className="flex items-center gap-2">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold transition-colors ${
                  done
                    ? "bg-brand text-brand-foreground"
                    : active
                      ? "bg-brand text-brand-foreground"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {done ? "\u2713" : i + 1}
              </div>
              <span
                className={`text-sm ${active ? "font-semibold text-foreground" : "text-muted-foreground"}`}
              >
                {t(step.labelKey)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
