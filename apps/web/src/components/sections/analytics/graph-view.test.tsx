import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test-utils";

const getKnowledgeGraph = vi.fn();

vi.mock("@/lib/api", () => ({
  getKnowledgeGraph: (...args: unknown[]) => getKnowledgeGraph(...args),
}));

vi.mock("@/lib/error-telemetry", () => ({
  trackApiFailure: vi.fn(),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

// Helper: load the module fresh after toggling NEXT_PUBLIC_ENABLE_LOOM,
// because the gate is read at module-eval time (build-time env). Each
// branch needs its own dynamic import.
async function loadGraphView() {
  const mod = await import("./graph-view");
  return mod.GraphView;
}

describe("GraphView", () => {
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
    const GraphView = await loadGraphView();

    render(<GraphView courseId="course-1" />);

    await screen.findByText(
      "Knowledge Graph (LOOM) is an experimental feature.",
    );
    expect(getKnowledgeGraph).not.toHaveBeenCalled();
  });

  it("renders empty state when LOOM is enabled but graph has no nodes", async () => {
    process.env.NEXT_PUBLIC_ENABLE_LOOM = "true";
    getKnowledgeGraph.mockResolvedValue({ nodes: [], edges: [] });
    const GraphView = await loadGraphView();

    render(<GraphView courseId="course-1" />);

    await screen.findByText("graph.emptyHint");
    expect(getKnowledgeGraph).toHaveBeenCalledWith("course-1");
  });
});
