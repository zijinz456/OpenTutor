"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

interface ThemeToggleProps {
  t: (key: string) => string;
}

/**
 * Light/dark switch for the setup wizard. The icon is chosen with the `dark:`
 * variant rather than from `resolvedTheme`, so server and client render the
 * same markup and there is no hydration mismatch.
 */
export function ThemeToggle({ t }: ThemeToggleProps) {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      data-testid="setup-theme-toggle"
      aria-label={t("setup.toggleTheme")}
      title={t("setup.toggleTheme")}
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      <Sun aria-hidden="true" className="dark:hidden" />
      <Moon aria-hidden="true" className="hidden dark:block" />
    </Button>
  );
}
