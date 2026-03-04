import { useT } from "@/lib/i18n-context";

interface StepNavigationProps {
  currentStep: number;
  totalSteps: number;
  saving: boolean;
  canAdvance: boolean;
  onBack: () => void;
  onNext: () => void;
}

export function StepNavigation({
  currentStep,
  totalSteps,
  saving,
  canAdvance,
  onBack,
  onNext,
}: StepNavigationProps) {
  const t = useT();
  const isLastStep = currentStep === totalSteps - 1;

  let nextLabel: string;
  if (isLastStep) {
    nextLabel = saving ? t("onboarding.saving") : t("onboarding.finish");
  } else {
    nextLabel = `${t("onboarding.continue")} \u2192`;
  }

  return (
    <div className="flex justify-between">
      {currentStep > 0 ? (
        <button
          type="button"
          onClick={onBack}
          className="h-11 px-6 border border-border rounded-lg flex items-center gap-1.5 text-muted-foreground font-medium text-sm hover:border-foreground/30 transition-colors"
        >
          &larr; {t("onboarding.back")}
        </button>
      ) : (
        <div />
      )}

      <button
        type="button"
        onClick={onNext}
        disabled={!canAdvance}
        className="h-11 px-8 bg-brand text-brand-foreground font-semibold text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed rounded-lg hover:opacity-90"
      >
        {nextLabel}
      </button>
    </div>
  );
}
