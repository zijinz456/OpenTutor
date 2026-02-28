"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Globe, Moon, Palette, RefreshCw, Sun } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { setLocale, getLocale, type Locale } from "@/lib/i18n";
import { useT } from "@/lib/i18n-context";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Template {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  target_audience: string;
  tags: string[];
  preferences: Record<string, string>;
}

export default function SettingsPage() {
  const router = useRouter();
  const t = useT();
  const { theme, setTheme } = useTheme();
  const [locale, setLocaleState] = useState<Locale>("en");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [applying, setApplying] = useState<string | null>(null);

  useEffect(() => {
    setLocaleState(getLocale());
    loadTemplates();
  }, []);

  const loadTemplates = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/progress/templates`);
      if (res.ok) setTemplates(await res.json());
    } catch {
      // Templates may not be seeded yet
    }
  };

  const handleLocaleChange = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleState(newLocale);
    toast.success(newLocale === "zh" ? "已切换到中文" : "Switched to English");
  };

  const handleApplyTemplate = async (templateId: string) => {
    setApplying(templateId);
    try {
      const res = await fetch(`${API_BASE}/api/progress/templates/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template_id: templateId }),
      });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Applied "${data.template}" template (${data.applied_preferences} preferences)`);
      }
    } catch {
      toast.error("Failed to apply template");
    } finally {
      setApplying(null);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-3 flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold">{t("nav.settings")}</h1>
      </header>

      <div className="max-w-2xl mx-auto p-6 space-y-8">
        {/* Language */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Globe className="h-4 w-4" />
            <h2 className="font-medium">{t("pref.language")}</h2>
          </div>
          <div className="flex gap-2">
            <Button
              variant={locale === "en" ? "default" : "outline"}
              size="sm"
              onClick={() => handleLocaleChange("en")}
            >
              English
            </Button>
            <Button
              variant={locale === "zh" ? "default" : "outline"}
              size="sm"
              onClick={() => handleLocaleChange("zh")}
            >
              中文
            </Button>
          </div>
        </section>

        {/* Appearance */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Palette className="h-4 w-4" />
            <h2 className="font-medium">Appearance</h2>
          </div>
          <div className="flex gap-2">
            <Button
              variant={theme === "light" ? "default" : "outline"}
              size="sm"
              onClick={() => setTheme("light")}
            >
              <Sun className="h-3.5 w-3.5 mr-1" />
              Light
            </Button>
            <Button
              variant={theme === "dark" ? "default" : "outline"}
              size="sm"
              onClick={() => setTheme("dark")}
            >
              <Moon className="h-3.5 w-3.5 mr-1" />
              Dark
            </Button>
            <Button
              variant={theme === "system" ? "default" : "outline"}
              size="sm"
              onClick={() => setTheme("system")}
            >
              System
            </Button>
          </div>
        </section>

        {/* Learning Templates */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Palette className="h-4 w-4" />
            <h2 className="font-medium">Learning Templates</h2>
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            Apply a template to set your learning preferences. You can always customize later.
          </p>
          <div className="grid gap-3">
            {templates.map((template) => (
              <div
                key={template.id}
                className="border rounded-lg p-4 flex items-start justify-between"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm">{template.name}</span>
                    {template.is_builtin && (
                      <Badge variant="secondary" className="text-xs">Built-in</Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mb-2">
                    {template.description}
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {template.tags?.map((tag) => (
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
                  {applying === template.id ? (
                    <RefreshCw className="h-3 w-3 animate-spin" />
                  ) : (
                    "Apply"
                  )}
                </Button>
              </div>
            ))}
            {templates.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No templates available. They will be created on first server start.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
