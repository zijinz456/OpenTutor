import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { SearchDialog } from "./search-dialog";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

const MOCK_TREE = [
  {
    id: "n1",
    title: "Introduction to Accounting",
    type: "page",
    content: "This chapter covers basic accounting principles and concepts.",
    children: [],
  },
  {
    id: "n2",
    title: "Financial Statements",
    type: "week",
    content: "Learn about balance sheets and income statements.",
    children: [
      {
        id: "n3",
        title: "Balance Sheet Deep Dive",
        type: "page",
        content: "Assets, liabilities, and equity explained in detail.",
        children: [],
      },
    ],
  },
];

vi.mock("@/store/course", () => ({
  useCourseStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      contentTree: MOCK_TREE,
      courses: [{ id: "course-1" }],
    }),
}));

describe("SearchDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <SearchDialog open={false} onClose={vi.fn()} courseId="course-1" />
    );
    expect(container.querySelector("[role='dialog']")).not.toBeInTheDocument();
  });

  it("renders dialog when open", () => {
    render(<SearchDialog open={true} onClose={vi.fn()} courseId="course-1" />);
    expect(
      screen.getByRole("dialog", { name: "Search notes and concepts" })
    ).toBeInTheDocument();
  });

  it("renders search input with placeholder", () => {
    render(<SearchDialog open={true} onClose={vi.fn()} courseId="course-1" />);
    expect(screen.getByPlaceholderText("Search notes, concepts...")).toBeInTheDocument();
  });

  it("shows prompt text when no query entered", () => {
    render(<SearchDialog open={true} onClose={vi.fn()} courseId="course-1" />);
    expect(
      screen.getByText("Type to search through your notes and concepts")
    ).toBeInTheDocument();
  });

  it("shows matching results when query is entered", async () => {
    const { user } = render(
      <SearchDialog open={true} onClose={vi.fn()} courseId="course-1" />
    );
    const input = screen.getByPlaceholderText("Search notes, concepts...");
    await user.type(input, "Accounting");
    await waitFor(() => {
      expect(screen.getByText("Introduction to Accounting")).toBeInTheDocument();
    });
  });

  it("shows no results message for unmatched query", async () => {
    const { user } = render(
      <SearchDialog open={true} onClose={vi.fn()} courseId="course-1" />
    );
    const input = screen.getByPlaceholderText("Search notes, concepts...");
    await user.type(input, "zzzznotfound");
    await waitFor(() => {
      expect(screen.getByText(/No results found/)).toBeInTheDocument();
    });
  });
});
