import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MissionHeader } from "./mission-header";

// `next/link` is a client-only component and Next's stub in tests
// happily forwards href — no extra mock needed beyond the default
// vitest setup.

// Shim useRouter-style imports if they leak in — harmless if unused.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("<MissionHeader>", () => {
  it("renders breadcrumb + chips for a fully-populated mission", () => {
    render(
      <MissionHeader
        pathSlug="python-fundamentals"
        pathTitle="Python Fundamentals"
        missionTitle="For loops"
        difficulty={3}
        etaMinutes={20}
        moduleLabel="Basics"
      />,
    );

    expect(screen.getByTestId("mission-header")).toBeInTheDocument();
    expect(screen.getByTestId("mission-header-breadcrumb-tracks").textContent)
      .toBe("Tracks");
    expect(screen.getByTestId("mission-header-breadcrumb-path").textContent)
      .toBe("Python Fundamentals");
    expect(
      screen.getByTestId("mission-header-breadcrumb-mission").textContent,
    ).toBe("For loops");

    expect(screen.getByTestId("mission-header-chip-module").textContent).toBe(
      "Basics",
    );
    expect(
      screen.getByTestId("mission-header-chip-difficulty").textContent,
    ).toBe("3/5");
    expect(screen.getByTestId("mission-header-chip-eta").textContent).toBe(
      "20 min",
    );
  });

  it("omits chips when their underlying fields are null", () => {
    render(
      <MissionHeader
        pathSlug="hacking-foundations"
        pathTitle="Hacking"
        missionTitle="Juice Shop"
        difficulty={null}
        etaMinutes={null}
        moduleLabel={null}
      />,
    );
    expect(screen.queryByTestId("mission-header-chip-module")).toBeNull();
    expect(screen.queryByTestId("mission-header-chip-difficulty")).toBeNull();
    expect(screen.queryByTestId("mission-header-chip-eta")).toBeNull();
    // Breadcrumb still renders.
    expect(screen.getByTestId("mission-header-breadcrumb-mission").textContent)
      .toBe("Juice Shop");
  });

  it("breadcrumb path link points at /tracks/{slug}", () => {
    render(
      <MissionHeader
        pathSlug="python-fundamentals"
        pathTitle="Python"
        missionTitle="Loops"
        difficulty={2}
        etaMinutes={15}
        moduleLabel="Basics"
      />,
    );
    const pathLink = screen.getByTestId("mission-header-breadcrumb-path");
    expect(pathLink.getAttribute("href")).toBe("/tracks/python-fundamentals");
  });
});
