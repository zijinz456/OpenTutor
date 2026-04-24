import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { LocaleProvider } from "@/lib/i18n-context";
import { useBadDayStore } from "@/store/bad-day";

import { BadDayToggle } from "./bad-day-toggle";

function renderWithProvider(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>);
}

describe("<BadDayToggle>", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-24T12:00:00.000Z"));
    window.localStorage.clear();
    useBadDayStore.setState({ active: false, activated_date: "" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("toggles the store on and shows the banner", () => {
    renderWithProvider(<BadDayToggle />);

    fireEvent.click(screen.getByTestId("bad-day-toggle-button"));

    expect(useBadDayStore.getState().isActiveToday()).toBe(true);
    expect(screen.getByTestId("bad-day-toggle-banner")).toBeInTheDocument();
  });
});
