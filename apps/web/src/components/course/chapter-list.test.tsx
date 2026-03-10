import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test-utils";
import { ChapterList } from "./chapter-list";
import type { ContentNode } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
  useTF: () => (key: string, params?: Record<string, unknown>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}));

const MOCK_NODES: ContentNode[] = [
  {
    id: "node-1",
    title: "Week 1: Introduction",
    type: "week",
    content: "",
    children: [
      { id: "child-1", title: "Lecture 1", type: "page", content: "", children: [] },
      { id: "child-2", title: "Lecture 2", type: "page", content: "", children: [] },
    ],
  },
  {
    id: "node-2",
    title: "Week 2: Advanced Topics",
    type: "week",
    content: "",
    children: [],
  },
  {
    id: "node-3",
    title: "Reading Material",
    type: "page",
    content: "",
    children: [],
  },
];

describe("ChapterList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders chapter titles", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    expect(screen.getByText("Week 1: Introduction")).toBeInTheDocument();
    expect(screen.getByText("Week 2: Advanced Topics")).toBeInTheDocument();
    expect(screen.getByText("Reading Material")).toBeInTheDocument();
  });

  it("renders empty state when no nodes", () => {
    render(<ChapterList courseId="test" nodes={[]} />);
    expect(screen.getByText("chapter.empty")).toBeInTheDocument();
  });

  it("has navigation role with aria-label", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    expect(screen.getByRole("navigation", { name: "Course chapters" })).toBeInTheDocument();
  });

  it("renders list items with correct links", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    const items = screen.getAllByRole("treeitem");
    expect(items).toHaveLength(3);
    // Each item should link to the unit page
    const link = items[0].querySelector("a");
    expect(link).toHaveAttribute("href", "/course/test/unit/node-1");
  });

  it("shows section count for nodes with children", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    // Node-1 has 2 children, should show section count
    expect(screen.getByText(/chapter\.sections/)).toBeInTheDocument();
  });

  it("does not show section count for leaf nodes", () => {
    render(<ChapterList courseId="test" nodes={[MOCK_NODES[2]]} />);
    // Reading Material has no children
    expect(screen.queryByText(/chapter\.sections/)).not.toBeInTheDocument();
  });
});
