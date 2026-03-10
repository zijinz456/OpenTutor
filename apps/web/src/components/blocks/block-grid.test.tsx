import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test-utils";
import { BlockGrid } from "./block-grid";

vi.mock("@/hooks/use-roving-tabindex", () => ({
  useRovingTabindex: vi.fn(),
}));

vi.mock("./block-wrapper", () => ({
  BlockWrapper: ({ block }: { block: { type: string } }) => (
    <div data-testid={`block-${block.type}`}>Block: {block.type}</div>
  ),
}));

vi.mock("./block-palette", () => ({
  BlockPalette: () => <div data-testid="block-palette" />,
}));

vi.mock("@/lib/block-system/registry", () => ({
  BLOCK_REGISTRY: {
    notes: { label: "Notes" },
    quiz: { label: "Quiz" },
    progress: { label: "Progress" },
  },
}));

const MOCK_BLOCKS = [
  { id: "b1", type: "notes", position: 0, size: "large", visible: true, source: "template", config: {} },
  { id: "b2", type: "quiz", position: 1, size: "medium", visible: true, source: "template", config: {} },
  { id: "b3", type: "progress", position: 2, size: "small", visible: false, source: "template", config: {} },
];

let mockBlocks = MOCK_BLOCKS;

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ spaceLayout: { blocks: mockBlocks, columns: 2 } }),
    {
      getState: () => ({ spaceLayout: { blocks: mockBlocks, columns: 2 } }),
    },
  ),
}));

describe("BlockGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockBlocks = MOCK_BLOCKS;
  });

  it("renders visible blocks as list items", () => {
    render(<BlockGrid courseId="test" aiActionsEnabled={false} />);
    const items = screen.getAllByRole("listitem");
    // Only 2 visible blocks (b3 is hidden)
    expect(items).toHaveLength(2);
  });

  it("has proper ARIA role=list with label", () => {
    render(<BlockGrid courseId="test" aiActionsEnabled={false} />);
    expect(screen.getByRole("list", { name: "Workspace blocks" })).toBeInTheDocument();
  });

  it("renders block content through BlockWrapper", () => {
    render(<BlockGrid courseId="test" aiActionsEnabled={false} />);
    expect(screen.getByTestId("block-notes")).toBeInTheDocument();
    expect(screen.getByTestId("block-quiz")).toBeInTheDocument();
  });

  it("returns null when no visible blocks exist", () => {
    mockBlocks = MOCK_BLOCKS.map((b) => ({ ...b, visible: false }));
    const { container } = render(<BlockGrid courseId="test" aiActionsEnabled={false} />);
    expect(container.querySelector("[role='list']")).not.toBeInTheDocument();
  });

  it("renders blocks sorted by position", () => {
    mockBlocks = [
      { id: "b2", type: "quiz", position: 1, size: "medium", visible: true, source: "template", config: {} },
      { id: "b1", type: "notes", position: 0, size: "large", visible: true, source: "template", config: {} },
    ];
    render(<BlockGrid courseId="test" aiActionsEnabled={false} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    // First item should be notes (position 0), second should be quiz (position 1)
    expect(items[0]).toHaveTextContent("notes");
    expect(items[1]).toHaveTextContent("quiz");
  });

  it("renders block palette for adding blocks", () => {
    render(<BlockGrid courseId="test" aiActionsEnabled={false} />);
    expect(screen.getByTestId("block-palette")).toBeInTheDocument();
  });
});
