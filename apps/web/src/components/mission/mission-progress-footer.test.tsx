import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MissionProgressFooter } from "./mission-progress-footer";

describe("<MissionProgressFooter>", () => {
  it("renders percentage and eta when both are available", () => {
    render(
      <MissionProgressFooter
        progressPct={58}
        etaMinutes={12}
        canPrev
        canNext
        onPrev={() => {}}
        onNext={() => {}}
      />,
    );
    const progress = screen.getByTestId("mission-progress-footer-progress");
    // Copy contract: `58% · 12 min` — dots separator, no em-dash, tabular.
    expect(progress.textContent).toContain("58%");
    expect(progress.textContent).toContain("12 min");
  });

  it("omits eta cleanly when etaMinutes is null", () => {
    render(
      <MissionProgressFooter
        progressPct={20}
        etaMinutes={null}
        canPrev={false}
        canNext
        onPrev={() => {}}
        onNext={() => {}}
      />,
    );
    const progress = screen.getByTestId("mission-progress-footer-progress");
    expect(progress.textContent).toContain("20%");
    expect(progress.textContent).not.toContain("min");
  });

  it("disables prev when canPrev is false, next when canNext is false", () => {
    const onPrev = vi.fn();
    const onNext = vi.fn();
    render(
      <MissionProgressFooter
        progressPct={0}
        etaMinutes={15}
        canPrev={false}
        canNext={false}
        onPrev={onPrev}
        onNext={onNext}
      />,
    );
    expect(
      screen.getByTestId("mission-progress-footer-prev"),
    ).toBeDisabled();
    expect(
      screen.getByTestId("mission-progress-footer-next"),
    ).toBeDisabled();
  });

  it("invokes onNext when the next button is clicked", async () => {
    const onNext = vi.fn();
    render(
      <MissionProgressFooter
        progressPct={40}
        etaMinutes={10}
        canPrev
        canNext
        onPrev={() => {}}
        onNext={onNext}
      />,
    );
    await userEvent.click(
      screen.getByTestId("mission-progress-footer-next"),
    );
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("is sticky-positioned via fixed bottom-0 utility", () => {
    render(
      <MissionProgressFooter
        progressPct={40}
        etaMinutes={10}
        canPrev
        canNext
        onPrev={() => {}}
        onNext={() => {}}
      />,
    );
    const footer = screen.getByTestId("mission-progress-footer");
    // Classlist contains `fixed` + `bottom-0` — we don't assert on
    // computed style because jsdom doesn't resolve Tailwind.
    expect(footer.className).toContain("fixed");
    expect(footer.className).toContain("bottom-0");
  });
});
