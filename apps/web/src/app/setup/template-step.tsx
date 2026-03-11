"use client";

import { GraduationCap, Compass, Clock, Shield, BookOpen, Brain, BarChart3, ListChecks, HelpCircle, Layers, AlertTriangle, Lightbulb, FileText } from "lucide-react";
import { TEMPLATE_LIST, LEARNING_MODE_LIST } from "@/lib/block-system/templates";
import type { LearningMode } from "@/lib/block-system/types";
import type { BlockType } from "@/lib/block-system/types";

const BLOCK_ICONS: Record<BlockType, typeof BookOpen> = {
  notes: FileText,
  quiz: HelpCircle,
  flashcards: Layers,
  progress: BarChart3,
  knowledge_graph: Brain,
  review: BookOpen,
  chapter_list: ListChecks,
  plan: ListChecks,
  wrong_answers: AlertTriangle,
  forecast: BarChart3,
  agent_insight: Lightbulb,
};

const MODE_ICONS: Record<LearningMode, typeof GraduationCap> = {
  course_following: GraduationCap,
  self_paced: Compass,
  exam_prep: Clock,
  maintenance: Shield,
};

const MODE_COLORS: Record<LearningMode, { ring: string; bg: string; text: string }> = {
  course_following: { ring: "ring-brand/30", bg: "bg-brand-muted/30", text: "text-brand" },
  self_paced: { ring: "ring-info/30", bg: "bg-info-muted/30", text: "text-info" },
  exam_prep: { ring: "ring-warning/30", bg: "bg-warning-muted/30", text: "text-warning" },
  maintenance: { ring: "ring-success/30", bg: "bg-success-muted/30", text: "text-success" },
};

interface TemplateStepProps {
  selectedTemplate: string | null;
  onSelect: (id: string) => void;
  selectedMode: LearningMode | null;
  onModeSelect: (mode: LearningMode) => void;
  onConfirm: () => void;
  onBack: () => void;
  t: (key: string) => string;
}

export function TemplateStep({
  selectedTemplate,
  onSelect,
  selectedMode,
  onModeSelect,
  onConfirm,
  onBack,
  t,
}: TemplateStepProps) {
  return (
    <div className="space-y-6">
      {/* Learning Mode Selection */}
      <div>
        <h2 className="text-lg font-semibold text-foreground">
          {t("setup.modeTitle")}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {t("setup.modeDescription")}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        {LEARNING_MODE_LIST.map((m) => {
          const Icon = MODE_ICONS[m.id];
          const active = selectedMode === m.id;
          const colors = MODE_COLORS[m.id];
          return (
            <button
              type="button"
              key={m.id}
              onClick={() => onModeSelect(m.id)}
              className={`p-3 rounded-xl border text-left transition-all ${
                active
                  ? `border-transparent ${colors.bg} ring-1 ${colors.ring}`
                  : "border-border bg-card hover:border-muted-foreground/20"
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <Icon className={`size-4 ${active ? colors.text : "text-muted-foreground"}`} />
                <span className={`text-sm font-medium ${active ? "text-foreground" : "text-foreground"}`}>
                  {t(`mode.${m.id}`)}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground line-clamp-2">
                {t(`mode.${m.id}.desc`)}
              </p>
            </button>
          );
        })}
      </div>

      {/* Template Selection */}
      <div className="pt-2 border-t border-border">
        <h3 className="text-sm font-semibold text-foreground mb-1">
          {t("setup.templateTitle")}
        </h3>
        <p className="text-xs text-muted-foreground mb-3">
          {t("setup.templateDescription")}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-2.5">
        {TEMPLATE_LIST.map((tpl) => {
          const active = selectedTemplate === tpl.id;
          const blocks = tpl.blocks.filter((b) => b.type !== "chapter_list");
          return (
            <button
              type="button"
              key={tpl.id}
              onClick={() => onSelect(tpl.id)}
              className={`p-3 rounded-xl border text-left transition-colors ${
                active
                  ? "border-brand bg-brand-muted/30 ring-1 ring-brand/30"
                  : "border-border bg-card hover:border-brand/40 hover:bg-brand-muted/10"
              }`}
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground">
                    {t(`setup.template.${tpl.id}`)}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {t(`setup.template.${tpl.id}.desc`)}
                  </p>
                </div>
                {/* Visual block grid preview */}
                <div className="shrink-0 grid grid-cols-3 gap-0.5 w-[60px]">
                  {blocks.slice(0, 6).map((b, i) => {
                    const Icon = BLOCK_ICONS[b.type];
                    const w = b.size === "large" ? "col-span-2" : b.size === "full" ? "col-span-3" : "";
                    return (
                      <div
                        key={i}
                        className={`flex items-center justify-center rounded bg-muted/60 h-4 ${w}`}
                        title={b.type.replace(/_/g, " ")}
                      >
                        <Icon className="size-2.5 text-muted-foreground" />
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="flex gap-1 mt-2 flex-wrap">
                {blocks.map((b, i) => (
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
          {t("common.back")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={!selectedTemplate || !selectedMode}
          className="px-5 py-2 text-sm font-medium rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {t("setup.continue")}
        </button>
      </div>
    </div>
  );
}
