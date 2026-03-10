import { describe, it, expect } from "vitest";
import { useRef } from "react";
import { render, screen } from "@/test-utils";
import { useRovingTabindex } from "./use-roving-tabindex";

function RovingHarness({ orientation = "vertical" }: { orientation?: "horizontal" | "vertical" | "both" }) {
  const ref = useRef<HTMLDivElement>(null);
  useRovingTabindex(ref, orientation);
  return (
    <div ref={ref} data-testid="container">
      <div role="option" aria-selected={true} tabIndex={0} data-testid="item-0">A</div>
      <div role="option" aria-selected={false} tabIndex={-1} data-testid="item-1">B</div>
      <div role="option" aria-selected={false} tabIndex={-1} data-testid="item-2">C</div>
    </div>
  );
}

describe("useRovingTabindex", () => {
  it("initializes first item with tabIndex=0 and rest with -1", () => {
    render(<RovingHarness />);
    expect(screen.getByTestId("item-0")).toHaveAttribute("tabindex", "0");
    expect(screen.getByTestId("item-1")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByTestId("item-2")).toHaveAttribute("tabindex", "-1");
  });

  it("moves focus down with ArrowDown in vertical mode", async () => {
    const { user } = render(<RovingHarness orientation="vertical" />);
    screen.getByTestId("item-0").focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(screen.getByTestId("item-1"));
    expect(screen.getByTestId("item-1")).toHaveAttribute("tabindex", "0");
    expect(screen.getByTestId("item-0")).toHaveAttribute("tabindex", "-1");
  });

  it("wraps around at the end", async () => {
    const { user } = render(<RovingHarness orientation="vertical" />);
    screen.getByTestId("item-0").focus();
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    // Should wrap back to item-0
    expect(document.activeElement).toBe(screen.getByTestId("item-0"));
  });

  it("moves focus up with ArrowUp", async () => {
    const { user } = render(<RovingHarness orientation="vertical" />);
    screen.getByTestId("item-0").focus();
    await user.keyboard("{ArrowUp}");
    // Should wrap to last item
    expect(document.activeElement).toBe(screen.getByTestId("item-2"));
  });

  it("supports Home and End keys", async () => {
    const { user } = render(<RovingHarness orientation="vertical" />);
    screen.getByTestId("item-0").focus();
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(screen.getByTestId("item-2"));
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(screen.getByTestId("item-0"));
  });

  it("uses ArrowRight/ArrowLeft in horizontal mode", async () => {
    const { user } = render(<RovingHarness orientation="horizontal" />);
    screen.getByTestId("item-0").focus();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(screen.getByTestId("item-1"));
    await user.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(screen.getByTestId("item-0"));
  });
});
