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
    level: 0,
    order_index: 0,
    source_type: "manual",
    content_category: "lecture_slides",
    children: [
      { id: "child-1", title: "Lecture 1", type: "page", content: "", level: 1, order_index: 0, source_type: "pdf", content_category: "lecture_slides", children: [] },
      { id: "child-2", title: "Tutorial 1", type: "page", content: "", level: 1, order_index: 1, source_type: "pdf", content_category: "lecture_slides", children: [] },
    ],
  },
  {
    id: "node-2",
    title: "Week 2: Advanced Topics",
    type: "week",
    content: "",
    level: 0,
    order_index: 1,
    source_type: "manual",
    content_category: "lecture_slides",
    children: [],
  },
  {
    id: "node-3",
    title: "Reading Material",
    type: "page",
    content: "some content",
    level: 0,
    order_index: 2,
    source_type: "pdf",
    content_category: "textbook",
    children: [],
  },
];

describe("ChapterList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders knowledge node titles", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    expect(screen.getByText("Week 1: Introduction")).toBeInTheDocument();
    expect(screen.getByText("Week 2: Advanced Topics")).toBeInTheDocument();
    expect(screen.getByText("Reading Material")).toBeInTheDocument();
  });

  it("renders empty state when no nodes", () => {
    render(<ChapterList courseId="test" nodes={[]} />);
    expect(screen.getByText("chapter.empty")).toBeInTheDocument();
  });

  it("filters out assignment/info leaf nodes", () => {
    const nodesWithAssignment: ContentNode[] = [
      ...MOCK_NODES,
      {
        id: "assignment-1",
        title: "Homework Submission",
        type: "page",
        content: null,
        level: 1,
        order_index: 3,
        source_type: "url",
        content_category: "assignment",
        children: [],
      },
    ];
    render(<ChapterList courseId="test" nodes={nodesWithAssignment} />);
    expect(screen.getByText("Week 1: Introduction")).toBeInTheDocument();
    expect(screen.queryByText("Homework Submission")).not.toBeInTheDocument();
  });

  it("keeps syllabus containers that have knowledge children", () => {
    const syllabusContainer: ContentNode[] = [
      {
        id: "root-1",
        title: "Course Root",
        type: "week",
        content: null,
        level: 0,
        order_index: 0,
        source_type: "url",
        content_category: "syllabus",
        children: [
          { id: "lec-1", title: "Lecture 1", type: "page", content: "slides", level: 1, order_index: 0, source_type: "pdf", content_category: "lecture_slides", children: [] },
        ],
      },
    ];
    render(<ChapterList courseId="test" nodes={syllabusContainer} />);
    expect(screen.getByText("Course Root")).toBeInTheDocument();
  });

  it("has navigation role with aria-label", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    expect(screen.getByRole("navigation", { name: "Course chapters" })).toBeInTheDocument();
  });

  it("renders tree items", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    const items = screen.getAllByRole("treeitem");
    expect(items).toHaveLength(3);
  });

  it("shows child count for folder nodes", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    expect(screen.getByText('chapter.sections:{"count":2}')).toBeInTheDocument();
  });

  it("renders correct links", () => {
    render(<ChapterList courseId="test" nodes={MOCK_NODES} />);
    const link = screen.getByText("Week 1: Introduction").closest("a");
    expect(link).toHaveAttribute("href", "/course/test/unit/node-1");
  });

  it("renders nodes without type field (real API shape)", () => {
    const apiNodes: ContentNode[] = [
      {
        id: "mod-1",
        title: "Module 1: Foundations",
        type: "" as ContentNode["type"],
        content: null,
        level: 0,
        order_index: 0,
        source_type: "canvas_module",
        content_category: null,
        children: [
          { id: "file-1", title: "Lecture 1.pdf", type: "" as ContentNode["type"], content: null, level: 1, order_index: 0, source_type: "pdf", content_category: null, children: [] },
        ],
      },
      {
        id: "mod-2",
        title: "Module 2: Advanced",
        type: "" as ContentNode["type"],
        content: null,
        level: 0,
        order_index: 1,
        source_type: "canvas_module",
        content_category: null,
        children: [],
      },
    ];
    render(<ChapterList courseId="test" nodes={apiNodes} />);
    expect(screen.getByText("Module 1: Foundations")).toBeInTheDocument();
    // Level-0 container with no children and no content is still shown
    expect(screen.getByText("Module 2: Advanced")).toBeInTheDocument();
  });
});
