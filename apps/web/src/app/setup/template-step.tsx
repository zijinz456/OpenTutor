"use client";

import { TEMPLATE_LIST } from "@/lib/block-system/templates";

interface TemplateStepProps {
  selectedTemplate: string | null;
  onSelect: (id: string) => void;
  onConfirm: () => void;
  onBack: () => void;
  t: (key: string) => string;
}

export function TemplateStep({
  selectedTemplate,
  onSelect,
  onConfirm,
  onBack,
  t,
}: TemplateStepProps) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-foreground">
          {t("setup.templateTitle") !== "setup.templateTitle"
            ? t("setup.templateTitle")
            : "Choose your layout"}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {t("setup.templateDescription") !== "setup.templateDescription"
            ? t("setup.templateDescription")
            : "Pick a template that fits your learning style. Your AI tutor will customize it over time."}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3">
        {TEMPLATE_LIST.map((tpl) => {
          const active = selectedTemplate === tpl.id;
          return (
            <button
              type="button"
              key={tpl.id}
              onClick={() => onSelect(tpl.id)}
              className={`p-4 rounded-xl border text-left transition-colors ${
                active
                  ? "border-brand bg-brand-muted/30 ring-1 ring-brand/30"
                  : "border-border bg-card hover:border-brand/40 hover:bg-brand-muted/10"
              }`}
            >
              <p className="text-sm font-medium text-foreground">{tpl.name}</p>
              <p className="text-xs text-muted-foreground mt-1">{tpl.description}</p>
              <div className="flex gap-1 mt-2 flex-wrap">
                {tpl.blocks
                  .filter((b) => b.type !== "chapter_list")
                  .map((b, i) => (
                    <span
                      key={i}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                    >
                      {b.type.replace(/_/g, " ")}
                    </span>
                  ))}
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          {t("common.back") !== "common.back" ? t("common.back") : "Back"}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={!selectedTemplate}
          className="px-5 py-2 text-sm font-medium rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {t("setup.continue") !== "setup.continue" ? t("setup.continue") : "Continue"}
        </button>
      </div>
    </div>
  );
}
