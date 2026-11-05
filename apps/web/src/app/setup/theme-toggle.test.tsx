import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "next-themes";
import type { ReactElement } from "react";
import { render, screen } from "@/test-utils";
import { t } from "@/lib/i18n";
import { ThemeToggle } from "./theme-toggle";

function renderToggle(): ReturnType<typeof render> {
  const ui: ReactElement = (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <ThemeToggle t={t} />
    </ThemeProvider>
  );
  return render(ui);
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
  });

  afterEach(() => {
    document.documentElement.className = "";
  });

  it("exposes a labelled button", () => {
    renderToggle();
    expect(
      screen.getByRole("button", { name: "Switch between light and dark mode" }),
    ).toBeInTheDocument();
  });

  it("switches from light to dark and back", async () => {
    const { user } = renderToggle();
    const button = screen.getByTestId("setup-theme-toggle");

    expect(document.documentElement).not.toHaveClass("dark");

    await user.click(button);
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("dark");

    await user.click(button);
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("switches to light when the stored theme is dark", async () => {
    localStorage.setItem("theme", "dark");
    const { user } = renderToggle();

    await user.click(screen.getByTestId("setup-theme-toggle"));

    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("light");
  });
});
