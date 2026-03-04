"use client";

import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { type Locale } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-context";

export function AppearanceSection() {
  const t = useT();
  const { locale, setLocale } = useLocale();
  const { theme, setTheme } = useTheme();

  function handleLocaleChange(newLocale: Locale): void {
    const message =
      newLocale === "zh"
        ? t("settings.languageChanged.zh")
        : t("settings.languageChanged.en");
    setLocale(newLocale);
    toast.success(message);
  }

  return (
    <>
      <section>
        <h2 className="font-medium text-foreground mb-3">
          {t("pref.language")}
        </h2>
        <div className="flex gap-2">
          <Button
            data-testid="settings-language-en"
            variant={locale === "en" ? "default" : "outline"}
            size="sm"
            onClick={() => handleLocaleChange("en")}
          >
            English
          </Button>
          <Button
            data-testid="settings-language-zh"
            variant={locale === "zh" ? "default" : "outline"}
            size="sm"
            onClick={() => handleLocaleChange("zh")}
          >
            中文
          </Button>
        </div>
      </section>

      <section>
        <h2 className="font-medium text-foreground mb-3">
          {t("settings.theme")}
        </h2>
        <div className="flex gap-2">
          <Button
            data-testid="settings-theme-light"
            variant={theme === "light" ? "default" : "outline"}
            size="sm"
            onClick={() => setTheme("light")}
          >
            {t("settings.appearance.light")}
          </Button>
          <Button
            data-testid="settings-theme-dark"
            variant={theme === "dark" ? "default" : "outline"}
            size="sm"
            onClick={() => setTheme("dark")}
          >
            {t("settings.appearance.dark")}
          </Button>
          <Button
            data-testid="settings-theme-system"
            variant={theme === "system" ? "default" : "outline"}
            size="sm"
            onClick={() => setTheme("system")}
          >
            {t("settings.appearance.system")}
          </Button>
        </div>
      </section>
    </>
  );
}
