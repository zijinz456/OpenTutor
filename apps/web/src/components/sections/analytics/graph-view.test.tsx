import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test-utils";
import { GraphView } from "./graph-view";

const getFeatureFlags = vi.fn();
const getKnowledgeGraph = vi.fn();

vi.mock("@/lib/api", () => ({
  getFeatureFlags: (...args: unknown[]) => getFeatureFlags(...args),
  getKnowledgeGraph: (...args: unknown[]) => getKnowledgeGraph(...args),
}));

vi.mock("@/lib/error-telemetry", () => ({
  trackApiFailure: vi.fn(),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

describe("GraphView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when LOOM is enabled but graph has no nodes", async () => {
    getFeatureFlags.mockResolvedValue({ loom: true });
    getKnowledgeGraph.mockResolvedValue({ nodes: [], edges: [] });

    render(<GraphView courseId="course-1" />);

    await screen.findByText("graph.emptyHint");
    expect(getKnowledgeGraph).toHaveBeenCalledWith("course-1");
  });

  it("shows experimental-gated message when LOOM is disabled", async () => {
    getFeatureFlags.mockResolvedValue({ loom: false });

    render(<GraphView courseId="course-1" />);

    await screen.findByText("Knowledge Graph (LOOM) is an experimental feature.");
    expect(getKnowledgeGraph).not.toHaveBeenCalled();
  });
});
