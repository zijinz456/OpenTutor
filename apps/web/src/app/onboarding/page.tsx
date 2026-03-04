"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { setPreference } from "@/lib/api";
import { toast } from "sonner";
import { useLocale, useT } from "@/lib/i18n-context";
import { buildSteps, buildOptionLabels } from "./types";
import { StepSidebar } from "./step-sidebar";
import { OptionStep } from "./option-step";
import { LayoutStep } from "./layout-step";
import { SummaryStep } from "./summary-step";
import { StepNavigation } from "./step-navigation";

export default function OnboardingPage() {
  const router = useRouter();
  const t = useT();
  const { setLocale } = useLocale();
  const [currentStep, setCurrentStep] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const steps = useMemo(() => buildSteps(t), [t]);
  const optionLabels = useMemo(() => buildOptionLabels(steps), [steps]);

  const step = steps[currentStep];
  const selected = selections[step.dimension];

  const handleSelect = (value: string) => {
    if (step.dimension === "language" && (value === "en" || value === "zh")) {
      setLocale(value);
    }
    setSelections((current) => ({ ...current, [step.dimension]: value }));
  };

  const handleFinish = async () => {
    setSaving(true);
    try {
      for (const [dimension, value] of Object.entries(selections)) {
        await setPreference(dimension, value, "global", undefined, "onboarding");
      }
      const selectedLanguage = selections.language;
      if (selectedLanguage === "en" || selectedLanguage === "zh") {
        setLocale(selectedLanguage);
      }
      localStorage.setItem("opentutor_onboarded", "true");
      toast.success(t("onboarding.saved"));
      router.push("/");
    } catch {
      toast.error(t("onboarding.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const handleNext = () => {
    if (currentStep < steps.length - 1) {
      setCurrentStep((index) => index + 1);
      return;
    }
    void handleFinish();
  };

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep((index) => index - 1);
    }
  };

  function renderStepContent() {
    if (step.type === "upload") {
      return <SummaryStep selections={selections} optionLabels={optionLabels} />;
    }
    if (step.type === "layout") {
      return <LayoutStep options={step.options} selected={selected} onSelect={handleSelect} />;
    }
    return <OptionStep options={step.options} selected={selected} onSelect={handleSelect} />;
  }

  return (
    <div className="h-screen flex bg-sidebar">
      <StepSidebar
        steps={steps}
        currentStep={currentStep}
        onStepClick={setCurrentStep}
      />

      <main className="flex-1 bg-background rounded-tl-xl p-16 flex flex-col justify-center gap-8 overflow-y-auto">
        <div className="max-w-[560px] flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-3 duration-300" key={currentStep}>
          <div>
            <h1 className="text-[28px] font-bold text-foreground">
              {step.title}
            </h1>
            <p className="text-[15px] text-muted-foreground mt-2 max-w-[500px]">{step.subtitle}</p>
          </div>

          {renderStepContent()}

          <StepNavigation
            currentStep={currentStep}
            totalSteps={steps.length}
            saving={saving}
            canAdvance={step.type === "upload" || !!selected}
            onBack={handleBack}
            onNext={handleNext}
          />
        </div>
      </main>
    </div>
  );
}
