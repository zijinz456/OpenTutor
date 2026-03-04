"use client";

import { FEATURE_CARDS } from "./types";
import { StepIndicator } from "./step-indicator";

interface FeatureConfigStepProps {
  projectName: string;
  features: Record<string, boolean>;
  onToggleFeature: (id: string) => void;
  nlInput: string;
  onNlInputChange: (value: string) => void;
  onBack: () => void;
  onEnterWorkspace: () => void;
  t: (key: string) => string;
}

export function FeatureConfigStep({
  projectName,
  features,
  onToggleFeature,
  nlInput,
  onNlInputChange,
  onBack,
  onEnterWorkspace,
  t,
}: FeatureConfigStepProps) {
  return (
    <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
      {/* Top nav */}
      <div className="flex items-center gap-3">
        <button type="button" data-testid="new-back-features" onClick={onBack} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          &larr; {t("settings.back")}
        </button>
        <div className="w-px h-4 bg-border" />
        <span className="font-semibold text-sm text-foreground">
          {projectName || t("new.newProject")}
        </span>
        <div className="flex-1" />
        <StepIndicator currentStep="features" t={t} />
      </div>

      <div className="flex flex-col gap-2">
        <h1 className="text-[28px] font-bold text-foreground">
          {t("new.featureTitle")}
        </h1>
        <p className="text-[15px] text-muted-foreground">{t("new.featureSubtitle")}</p>
      </div>

      {/* Feature Cards -- 2-column grid */}
      <div className="grid grid-cols-2 gap-4">
        {FEATURE_CARDS.map((card) => (
          <FeatureCard
            key={card.id}
            card={card}
            selected={features[card.id]}
            onToggle={() => onToggleFeature(card.id)}
            t={t}
          />
        ))}
      </div>

      {/* NL Input */}
      <div className="flex flex-col gap-2.5">
        <span className="font-semibold text-[15px] text-foreground">
          {t("new.extraPrompt")}
        </span>
        <textarea
          data-testid="new-extra-prompt"
          className="w-full h-20 p-3 border border-border rounded-lg bg-background resize-none text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
          placeholder={t("new.extraPromptPlaceholder")}
          value={nlInput}
          onChange={(e) => onNlInputChange(e.target.value)}
        />
      </div>

      <div className="w-full h-px bg-border" />

      <div className="flex justify-end gap-4">
        <button type="button" onClick={onBack} className="h-11 px-6 border border-border rounded-lg text-muted-foreground font-medium text-sm hover:border-foreground/20">
          {t("settings.back")}
        </button>
        <button
          type="button"
          onClick={onEnterWorkspace}
          data-testid="enter-workspace"
          className="h-11 px-7 bg-brand text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm hover:opacity-90"
        >
          {t("new.enterWorkspace")} &rarr;
        </button>
      </div>
    </div>
  );
}

/* ---------- Sub-component ---------- */

interface FeatureCardProps {
  card: (typeof FEATURE_CARDS)[number];
  selected: boolean;
  onToggle: () => void;
  t: (key: string) => string;
}

function FeatureCard({ card, selected, onToggle, t }: FeatureCardProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      data-testid={`feature-card-${card.id}`}
      aria-pressed={selected}
      data-selected={selected ? "true" : "false"}
      className={`p-5 rounded-xl flex flex-col gap-3 text-left transition-all ${
        selected
          ? "border-2 border-brand"
          : "border border-border"
        } ${card.phase ? "opacity-60 cursor-default" : "hover:shadow-md"}`}
    >
      <div className="flex items-center gap-2.5 w-full">
        <span className="font-semibold text-base text-foreground flex-1">
          {t(card.labelKey)}
        </span>
        {card.phase && (
          <span className="h-[22px] px-2 bg-warning-muted rounded text-[11px] font-semibold text-warning flex items-center">
            {card.phase}
          </span>
        )}
        <div
          className={`w-[22px] h-[22px] rounded flex items-center justify-center shrink-0 ml-auto ${
            selected ? "bg-brand" : "border-2 border-border"
          }`}
        >
          {selected && <span className="text-[10px] text-brand-foreground font-bold">{"\u2713"}</span>}
        </div>
      </div>
      <p className="text-[13px] text-muted-foreground">{t(card.descriptionKey)}</p>
    </button>
  );
}
