"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";
import { applyTemplate, listTemplates, type LearningTemplate } from "@/lib/api";

export function TemplatesSection() {
  const t = useT();
  const [templates, setTemplates] = useState<LearningTemplate[]>([]);
  const [applying, setApplying] = useState<string | null>(null);

  useEffect(() => {
    void loadTemplates();
  }, []);

  async function loadTemplates(): Promise<void> {
    try {
      const data = await listTemplates();
      setTemplates(data);
    } catch {
      // Templates may not be seeded yet
    }
  }

  async function handleApplyTemplate(templateId: string): Promise<void> {
    setApplying(templateId);
    try {
      await applyTemplate(templateId);
      toast.success(t("settings.templateApplied"));
    } catch {
      toast.error(t("settings.templateApplyFailed"));
    } finally {
      setApplying(null);
    }
  }

  return (
    <section>
      <h2 className="font-medium text-foreground mb-3">
        {t("settings.templates")}
      </h2>
      <p className="text-sm text-muted-foreground mb-4">
        {t("settings.templatesDescription")}
      </p>
      <div className="grid gap-3">
        {templates.map((template) => (
          <div
            key={template.id}
            className="border border-border rounded-lg p-4 flex items-start justify-between"
          >
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-medium text-sm text-foreground">
                  {template.name}
                </span>
                {template.is_builtin && (
                  <Badge variant="secondary" className="text-xs">
                    {t("settings.builtin")}
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mb-2">
                {template.description}
              </p>
              <div className="flex flex-wrap gap-1">
                {template.tags?.map((tag: string) => (
                  <Badge key={tag} variant="outline" className="text-xs">
                    {tag}
                  </Badge>
                ))}
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleApplyTemplate(template.id)}
              disabled={applying === template.id}
            >
              {applying === template.id
                ? t("settings.applying")
                : t("settings.apply")}
            </Button>
          </div>
        ))}
        {templates.length === 0 && (
          <p className="text-sm text-muted-foreground py-4 text-center">
            {t("settings.templatesEmpty")}
          </p>
        )}
      </div>
    </section>
  );
}
