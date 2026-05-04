import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test-utils";

const getForgettingForecast = vi.fn();

vi.mock("@/lib/api", () => ({
  getForgettingForecast: (...args: unknown[]) => getForgettingForecast(...args),
}));

// Helper: load the module fresh after toggling NEXT_PUBLIC_ENABLE_LOOM,
// because the gate is read at module-eval time (build-time env). Each
// branch needs its own dynamic import.
async function loadForecastView() {
  const mod = await import("./forecast-view");
  return mod.ForecastView;
}

describe("ForecastView", () => {
  const ORIGINAL_ENV = process.env.NEXT_PUBLIC_ENABLE_LOOM;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  afterEach(() => {
    if (ORIGINAL_ENV === undefined) {
      delete process.env.NEXT_PUBLIC_ENABLE_LOOM;
    } else {
      process.env.NEXT_PUBLIC_ENABLE_LOOM = ORIGINAL_ENV;
    }
  });

  it("renders the experimental placeholder and skips the fetch when LOOM is gated off", async () => {
    delete process.env.NEXT_PUBLIC_ENABLE_LOOM;
    const ForecastView = await loadForecastView();

    render(<ForecastView courseId="course-1" />);

    await screen.findByText(
      "Forgetting Forecast (LOOM) is an experimental feature.",
    );
    expect(getForgettingForecast).not.toHaveBeenCalled();
  });

  it("renders empty state when LOOM is enabled but forecast has no items", async () => {
    process.env.NEXT_PUBLIC_ENABLE_LOOM = "true";
    getForgettingForecast.mockResolvedValue({
      total_items: 0,
      urgent_count: 0,
      warning_count: 0,
      predictions: [],
    });
    const ForecastView = await loadForecastView();

    render(<ForecastView courseId="course-1" />);

    await screen.findByText("No review data yet.");
    expect(getForgettingForecast).toHaveBeenCalledWith("course-1");
  });
});
