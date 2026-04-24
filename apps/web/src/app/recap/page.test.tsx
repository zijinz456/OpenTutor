import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LocaleProvider } from "@/lib/i18n-context";
import RecapPage from "./page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("concepts=Pointers|Loops|Iterators"),
}));

describe("/recap page", () => {
  it("renders the title, all 3 concepts, and the back link", () => {
    render(
      <LocaleProvider>
        <RecapPage />
      </LocaleProvider>,
    );

    expect(screen.getByTestId("recap-title")).toHaveTextContent(
      "What you last learned",
    );
    expect(screen.getByText("Pointers")).toBeInTheDocument();
    expect(screen.getByText("Loops")).toBeInTheDocument();
    expect(screen.getByText("Iterators")).toBeInTheDocument();
    expect(screen.getByTestId("recap-back")).toHaveAttribute("href", "/");
  });
});
