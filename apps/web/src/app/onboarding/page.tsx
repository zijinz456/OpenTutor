"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { setPreference } from "@/lib/api";
import { toast } from "sonner";
import { useLocale, useT } from "@/lib/i18n-context";

interface OnboardingOption {
  value: string;
  label: string;
  description: string;
}

interface OnboardingStep {
  title: string;
  subtitle: string;
  dimension: string;
  type?: "layout" | "upload";
  options: OnboardingOption[];
}

function getSummaryLabel(dimension: string, t: (key: string) => string) {
  if (dimension === "language") return t("onboarding.summary.language");
  if (dimension === "learning_mode") return t("onboarding.summary.learningMode");
  if (dimension === "detail_level") return t("onboarding.summary.detailLevel");
  if (dimension === "layout_preset") return t("onboarding.summary.layoutPreset");
  return dimension.replace(/_/g, " ");
}

export default function OnboardingPage() {
  const router = useRouter();
  const t = useT();
  const { setLocale } = useLocale();
  const [currentStep, setCurrentStep] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const steps = useMemo<OnboardingStep[]>(
    () => [
      {
        title: t("onboarding.language.title"),
        subtitle: t("onboarding.language.subtitle"),
        dimension: "language",
        options: [
          { value: "en", label: "English", description: t("onboarding.language.enDescription") },
          { value: "zh", label: "中文 (Chinese)", description: t("onboarding.language.zhDescription") },
          { value: "auto", label: t("lang.bilingual"), description: t("onboarding.language.autoDescription") },
        ],
      },
      {
        title: t("onboarding.learningMode.title"),
        subtitle: t("onboarding.learningMode.subtitle"),
        dimension: "learning_mode",
        options: [
          {
            value: "concept_first",
            label: t("onboarding.learningMode.conceptFirst"),
            description: t("onboarding.learningMode.conceptFirstDescription"),
          },
          {
            value: "practice_first",
            label: t("onboarding.learningMode.practiceFirst"),
            description: t("onboarding.learningMode.practiceFirstDescription"),
          },
          {
            value: "balanced",
            label: t("onboarding.learningMode.balanced"),
            description: t("onboarding.learningMode.balancedDescription"),
          },
        ],
      },
      {
        title: t("onboarding.detailLevel.title"),
        subtitle: t("onboarding.detailLevel.subtitle"),
        dimension: "detail_level",
        options: [
          {
            value: "concise",
            label: t("onboarding.detailLevel.concise"),
            description: t("onboarding.detailLevel.conciseDescription"),
          },
          {
            value: "balanced",
            label: t("onboarding.detailLevel.balanced"),
            description: t("onboarding.detailLevel.balancedDescription"),
          },
          {
            value: "detailed",
            label: t("onboarding.detailLevel.detailed"),
            description: t("onboarding.detailLevel.detailedDescription"),
          },
        ],
      },
      {
        title: t("onboarding.layout.title"),
        subtitle: t("onboarding.layout.subtitle"),
        dimension: "layout_preset",
        type: "layout",
        options: [
          {
            value: "balanced",
            label: t("onboarding.layout.balanced"),
            description: t("onboarding.layout.balancedDescription"),
          },
          {
            value: "notesFocused",
            label: t("onboarding.layout.notesFocused"),
            description: t("onboarding.layout.notesFocusedDescription"),
          },
          {
            value: "chatFocused",
            label: t("onboarding.layout.chatFocused"),
            description: t("onboarding.layout.chatFocusedDescription"),
          },
        ],
      },
      {
        title: t("onboarding.finish.title"),
        subtitle: t("onboarding.finish.subtitle"),
        dimension: "example_style",
        type: "upload",
        options: [],
      },
    ],
    [t],
  );

  const optionLabels = useMemo(
    () =>
      new Map(
        steps.flatMap((step) =>
          step.options.map((option) => [`${step.dimension}:${option.value}`, option.label] as const),
        ),
      ),
    [steps],
  );

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

  return (
    <div className="h-screen flex bg-sidebar">
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

            return (
              <button
                type="button"
                key={candidate.dimension}
                onClick={() => canClick && setCurrentStep(index)}
                className={`flex items-center gap-2.5 h-10 px-3 rounded-md transition-colors ${
                  isCurrent ? "bg-sidebar-accent" : isDone ? "bg-sidebar-accent/60" : ""
                } ${canClick ? "cursor-pointer" : "cursor-default"}`}
              >
                <div
                  className={`w-[22px] h-[22px] rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${
                    isDone
                      ? "bg-success text-success-foreground"
                      : isCurrent
                        ? "bg-sidebar-foreground text-sidebar"
                        : "border border-sidebar-border text-sidebar-foreground/50"
                  }`}
                >
                  {isDone ? "\u2713" : index + 1}
                </div>
                <span
                  className={`text-[13px] ${
                    isDone
                      ? "text-sidebar-foreground/60 font-medium"
                      : isCurrent
                        ? "text-sidebar-foreground font-semibold"
                        : "text-sidebar-foreground/40"
                  }`}
                >
                  {candidate.dimension === "language" && t("pref.language")}
                  {candidate.dimension === "learning_mode" && t("onboarding.sidebar.learningMode")}
                  {candidate.dimension === "detail_level" && t("onboarding.sidebar.outputFormat")}
                  {candidate.dimension === "layout_preset" && t("onboarding.sidebar.layoutTemplate")}
                  {candidate.dimension === "example_style" && t("onboarding.sidebar.finish")}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="flex-1 bg-background rounded-tl-xl p-16 flex flex-col justify-center gap-8 overflow-y-auto">
        <div className="max-w-[560px] flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-3 duration-300" key={currentStep}>
          <div>
            <h1 className="text-[28px] font-bold text-foreground">
              {step.title}
            </h1>
            <p className="text-[15px] text-muted-foreground mt-2 max-w-[500px]">{step.subtitle}</p>
          </div>

          {step.type !== "upload" && step.type !== "layout" && (
            <div className="flex flex-col gap-3">
              {step.options.map((option) => (
                <button
                  type="button"
                  key={option.value}
                  onClick={() => handleSelect(option.value)}
                  className={`flex items-center gap-3 p-4 px-5 rounded-[10px] text-left transition-all ${
                    selected === option.value
                      ? "border-2 border-brand"
                      : "border border-border hover:border-muted-foreground/30"
                  }`}
                >
                  <div
                    className={`w-5 h-5 rounded-full shrink-0 flex items-center justify-center ${
                      selected === option.value ? "bg-brand" : "border-2 border-border"
                    }`}
                  >
                    {selected === option.value && <div className="w-2 h-2 rounded-full bg-brand-foreground" />}
                  </div>
                  <div className="flex flex-col gap-1 flex-1">
                    <span className="font-semibold text-[15px] text-foreground">
                      {option.label}
                    </span>
                    <span className="text-[13px] text-muted-foreground">{option.description}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {step.type === "layout" && (
            <div className="flex gap-4">
              {step.options.map((option) => (
                <button
                  type="button"
                  key={option.value}
                  onClick={() => handleSelect(option.value)}
                  className={`flex-1 p-5 rounded-[10px] flex flex-col gap-3 text-left transition-all ${
                    selected === option.value
                      ? "border-2 border-brand"
                      : "border border-border hover:border-muted-foreground/30"
                  }`}
                >
                  <div className="w-full h-20 bg-background border border-border rounded-md flex overflow-hidden">
                    {option.value === "balanced" && (
                      <>
                        <div className="w-[10%] bg-sidebar" />
                        <div className="flex-1 border-r border-border" />
                        <div className="w-[35%]" />
                      </>
                    )}
                    {option.value === "notesFocused" && (
                      <>
                        <div className="w-[10%] bg-sidebar" />
                        <div className="flex-1" />
                      </>
                    )}
                    {option.value === "chatFocused" && (
                      <>
                        <div className="w-[10%] bg-sidebar" />
                        <div className="flex-1 border-r border-border" />
                        <div className="flex-1 border-r border-border" />
                        <div className="flex-1" />
                      </>
                    )}
                  </div>
                  <span className="font-semibold text-sm text-foreground text-center w-full">
                    {option.label}
                  </span>
                  <span className="text-xs text-muted-foreground text-center w-full">{option.description}</span>
                </button>
              ))}
            </div>
          )}

          {step.type === "upload" && (
            <div className="flex flex-col gap-4">
              <div className="w-full p-6 border border-border rounded-[10px] bg-muted flex flex-col gap-3">
                <span className="text-sm font-medium text-foreground">{t("onboarding.summary.title")}</span>
                {Object.entries(selections).map(([dimension, value]) => (
                  <div key={dimension} className="flex items-center gap-2">
                    <span className="text-success text-xs shrink-0">{"\u2713"}</span>
                    <span className="text-[13px] text-muted-foreground">
                      {getSummaryLabel(dimension, t)}:{" "}
                      <span className="font-medium text-foreground">
                        {optionLabels.get(`${dimension}:${value}`) ?? value.replace(/_/g, " ")}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[13px] text-muted-foreground text-center">{t("onboarding.summary.later")}</p>
            </div>
          )}

          <div className="flex justify-between">
            {currentStep > 0 ? (
              <button
                type="button"
                onClick={handleBack}
                className="h-11 px-6 border border-border rounded-lg flex items-center gap-1.5 text-muted-foreground font-medium text-sm hover:border-foreground/30 transition-colors"
              >
                &larr; {t("onboarding.back")}
              </button>
            ) : (
              <div />
            )}

            <button
              type="button"
              onClick={handleNext}
              disabled={step.type !== "upload" && !selected}
              className="h-11 px-8 bg-brand text-brand-foreground font-semibold text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed rounded-lg hover:opacity-90"
            >
              {currentStep === steps.length - 1
                ? (saving ? t("onboarding.saving") : t("onboarding.finish"))
                : t("onboarding.continue")}
              {currentStep < steps.length - 1 && " \u2192"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
