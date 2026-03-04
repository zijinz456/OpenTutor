export interface OnboardingOption {
  value: string;
  label: string;
  description: string;
}

export interface OnboardingStep {
  title: string;
  subtitle: string;
  dimension: string;
  type?: "layout" | "upload";
  options: OnboardingOption[];
}

export function getSummaryLabel(dimension: string, t: (key: string) => string): string {
  if (dimension === "language") return t("onboarding.summary.language");
  if (dimension === "learning_mode") return t("onboarding.summary.learningMode");
  if (dimension === "detail_level") return t("onboarding.summary.detailLevel");
  if (dimension === "layout_preset") return t("onboarding.summary.layoutPreset");
  return dimension.replace(/_/g, " ");
}

export function buildSteps(t: (key: string) => string): OnboardingStep[] {
  return [
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
  ];
}

export function buildOptionLabels(steps: OnboardingStep[]): Map<string, string> {
  return new Map(
    steps.flatMap((step) =>
      step.options.map((option) => [`${step.dimension}:${option.value}`, option.label] as const),
    ),
  );
}
