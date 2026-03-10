"use client";

import { TEMPLATE_LIST } from "@/lib/block-system/templates";
import { useT } from "@/lib/i18n-context";

export function TemplatePicker({
  onApplyTemplate,
}: {
  onApplyTemplate: (templateId: string) => void;
}) {
  const t = useT();

  return (
    <section>
      <h2 className="text-lg font-semibold mb-3">{t("course.template.title")}</h2>
      <p className="text-sm text-muted-foreground mb-4">
        {t("course.template.subtitle")}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {TEMPLATE_LIST.map((t) => (
          <button
            type="button"
            key={t.id}
            onClick={() => onApplyTemplate(t.id)}
            className="p-5 rounded-2xl bg-card card-lift text-left group"
          >
            <p className="text-sm font-medium text-foreground">{t.name}</p>
            <p className="text-xs text-muted-foreground mt-1">{t.description}</p>
            <div className="flex gap-1 mt-2 flex-wrap">
              {t.blocks
                .filter((b) => b.type !== "chapter_list")
                .map((b, i) => (
                  <span
                    key={i}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground"
                  >
                    {b.type.replace("_", " ")}
                  </span>
                ))}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
