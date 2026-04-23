import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@/test-utils";
import { StrictModeToggle } from "./StrictModeToggle";
import { useChatStore } from "@/store/chat";

// Radix Tooltip renders a portal; replace with a passthrough so the trigger
// button lives in the normal DOM tree and we can query it by role.
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="tooltip-content">{children}</div>
  ),
}));

describe("StrictModeToggle", () => {
  beforeEach(() => {
    // Reset both localStorage and the persisted store state between tests —
    // useChatStore is a module-level singleton so it survives renders.
    window.localStorage.clear();
    useChatStore.setState({ strictMode: false });
  });

  it("renders the neutral gray pill by default (strict OFF)", () => {
    render(<StrictModeToggle />);
    const toggle = screen.getByTestId("strict-mode-toggle");
    expect(toggle).toHaveAttribute("data-state", "off");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toHaveTextContent("Strict off");
  });

  it("toggles state AND writes to localStorage when clicked", async () => {
    const { user } = render(<StrictModeToggle />);
    const toggle = screen.getByTestId("strict-mode-toggle");

    await user.click(toggle);

    expect(useChatStore.getState().strictMode).toBe(true);
    expect(window.localStorage.getItem("guardrails_strict")).toBe("true");
    expect(toggle).toHaveAttribute("data-state", "on");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveTextContent("Strict");

    await user.click(toggle);

    expect(useChatStore.getState().strictMode).toBe(false);
    expect(window.localStorage.getItem("guardrails_strict")).toBe("false");
  });

  it("loads strict=true from localStorage on mount", () => {
    // Simulate a previous-tab write, then rehydrate the store from storage
    // exactly the way module load would.
    window.localStorage.setItem("guardrails_strict", "true");
    useChatStore.setState({
      strictMode: window.localStorage.getItem("guardrails_strict") === "true",
    });

    render(<StrictModeToggle />);

    const toggle = screen.getByTestId("strict-mode-toggle");
    expect(toggle).toHaveAttribute("data-state", "on");
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});
