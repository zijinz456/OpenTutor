import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrutalDrillCTA } from "./brutal-drill-cta";

const mockPush = vi.fn();
const mockSearchParamsGet = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => ({
    get: (key: string) => mockSearchParamsGet(key),
  }),
}));

describe("<BrutalDrillCTA>", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockSearchParamsGet.mockReset();
    mockSearchParamsGet.mockReturnValue(null);
    window.localStorage.clear();
  });

  it("first click shows onboarding modal; Continue+dontShowAgain sets localStorage flag", async () => {
    const user = userEvent.setup();
    render(<BrutalDrillCTA />);

    // Clean localStorage → first click shows onboarding, not picker.
    await user.click(screen.getByTestId("brutal-drill-cta-button"));
    expect(screen.getByTestId("brutal-drill-onboarding")).toBeInTheDocument();
    expect(screen.queryByTestId("brutal-drill-picker")).toBeNull();

    // "Don't show again" defaults to checked — advance onto picker, flag
    // should land in localStorage.
    await user.click(screen.getByTestId("brutal-drill-onboarding-continue"));
    expect(window.localStorage.getItem("brutal_onboarding_seen")).toBe("true");
    expect(screen.queryByTestId("brutal-drill-onboarding")).toBeNull();
    expect(screen.getByTestId("brutal-drill-picker")).toBeInTheDocument();
  });

  it("subsequent clicks skip onboarding and open picker directly", async () => {
    window.localStorage.setItem("brutal_onboarding_seen", "true");
    const user = userEvent.setup();
    render(<BrutalDrillCTA />);

    await user.click(screen.getByTestId("brutal-drill-cta-button"));
    expect(screen.queryByTestId("brutal-drill-onboarding")).toBeNull();
    expect(screen.getByTestId("brutal-drill-picker")).toBeInTheDocument();

    // Pick 50 cards × 60s and Start → router.push with querystring.
    await user.click(screen.getByTestId("brutal-drill-size-50"));
    await user.click(screen.getByTestId("brutal-drill-timeout-60"));
    await user.click(screen.getByTestId("brutal-drill-picker-start"));
    expect(mockPush).toHaveBeenCalledWith("/session/brutal?size=50&timeout=60");
  });
});
