import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MissionPage from "./page";
import type { RoomDetailResponse } from "@/lib/api";

// Mock useParams so the page resolves slug + missionId without a
// router context.
vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "python-fundamentals", missionId: "mission-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// Mock getRoomDetail — each test configures the response shape.
const getRoomDetailMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getRoomDetail: (...args: unknown[]) => getRoomDetailMock(...args),
  };
});

// Stub the interactive TaskRenderer — Monaco + pyodide are too heavy
// for this SSR-style smoke. We only need to confirm the right task
// is routed into the practice pane.
vi.mock("@/components/path/RoomTaskList", async () => {
  const actual = await vi.importActual<
    typeof import("@/components/path/RoomTaskList")
  >("@/components/path/RoomTaskList");
  return {
    ...actual,
    TaskRenderer: ({ task }: { task: { id: string; question: string } }) => (
      <div data-testid={`task-renderer-stub-${task.id}`}>
        renderer:{task.id}
      </div>
    ),
  };
});

function buildResponse(
  overrides: Partial<RoomDetailResponse> = {},
): RoomDetailResponse {
  return {
    id: "mission-1",
    slug: "loops",
    title: "For loops",
    room_order: 0,
    intro_excerpt: "For loops iterate over a sequence.",
    outcome: "Write a loop that filters a list",
    difficulty: 3,
    eta_minutes: 20,
    module_label: "Basics",
    path_id: "path-1",
    path_slug: "python-fundamentals",
    path_title: "Python Fundamentals",
    task_total: 3,
    task_complete: 1,
    capstone_problem_ids: [],
    tasks: [
      {
        id: "t1",
        task_order: 0,
        question_type: "mc",
        question: "Intro",
        options: null,
        is_complete: true,
        difficulty_layer: null,
      },
      {
        id: "t2",
        task_order: 1,
        question_type: "mc",
        question: "Syntax",
        options: null,
        is_complete: false,
        difficulty_layer: null,
      },
      {
        id: "t3",
        task_order: 2,
        question_type: "mc",
        question: "Filter",
        options: null,
        is_complete: false,
        difficulty_layer: null,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  getRoomDetailMock.mockReset();
});

describe("MissionPage (3-pane)", () => {
  it("renders the mission-header, task sidebar, content, and practice panes after load", async () => {
    getRoomDetailMock.mockResolvedValueOnce(buildResponse());
    render(<MissionPage />);

    // Header renders with the path title from the response.
    await waitFor(() => {
      expect(screen.getByTestId("mission-header")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("mission-header-breadcrumb-path").textContent,
    ).toBe("Python Fundamentals");

    // Content pane shows the real intro_excerpt (not placeholder).
    expect(screen.getByTestId("mission-intro-excerpt").textContent).toBe(
      "For loops iterate over a sequence.",
    );

    // Task sidebar renders three rows — there are TWO sidebars in the
    // DOM (one mobile accordion, one xl+ column). Both list t1 and t2,
    // so getAllByTestId returns length 2 for each.
    expect(screen.getAllByTestId("task-sidebar-item-t1")).toHaveLength(2);
    expect(screen.getAllByTestId("task-sidebar-item-t2")).toHaveLength(2);

    // Progress footer — 1 of 3 tasks complete → 33%, eta 20.
    const progress = screen.getByTestId("mission-progress-footer-progress");
    expect(progress.textContent).toContain("33%");
    expect(progress.textContent).toContain("20 min");
  });

  it("selects the first non-complete task by default (t2)", async () => {
    getRoomDetailMock.mockResolvedValueOnce(buildResponse());
    render(<MissionPage />);
    // The practice pane stub receives the currentTask id — confirm t2
    // (since t1 is already is_complete).
    await waitFor(() => {
      expect(
        screen.getByTestId("task-renderer-stub-t2"),
      ).toBeInTheDocument();
    });
  });

  it("clicking a sidebar task swaps the practice pane target", async () => {
    getRoomDetailMock.mockResolvedValueOnce(buildResponse());
    render(<MissionPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("task-renderer-stub-t2"),
      ).toBeInTheDocument();
    });

    // Clicking in the xl-only sidebar is fine; both sidebars share
    // handlers and target the same state.
    const rows = screen.getAllByTestId("task-sidebar-item-t3");
    await userEvent.click(rows[0]);

    await waitFor(() => {
      expect(
        screen.getByTestId("task-renderer-stub-t3"),
      ).toBeInTheDocument();
    });
  });

  it("hides the checkpoint section when capstone_problem_ids is empty", async () => {
    getRoomDetailMock.mockResolvedValueOnce(buildResponse());
    render(<MissionPage />);
    await waitFor(() => {
      expect(screen.getByTestId("mission-header")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("checkpoint-section")).toBeNull();
  });

  it("renders the checkpoint section with one item per capstone id", async () => {
    getRoomDetailMock.mockResolvedValueOnce(
      buildResponse({ capstone_problem_ids: ["t3"] }),
    );
    render(<MissionPage />);
    await waitFor(() => {
      expect(screen.getByTestId("checkpoint-section")).toBeInTheDocument();
    });
    expect(screen.getByTestId("checkpoint-item-t3")).toBeInTheDocument();
  });

  it("shows the error banner when the fetch fails", async () => {
    getRoomDetailMock.mockRejectedValueOnce(new Error("offline"));
    render(<MissionPage />);
    await waitFor(() => {
      expect(screen.getByTestId("mission-page-error")).toBeInTheDocument();
    });
  });
});
