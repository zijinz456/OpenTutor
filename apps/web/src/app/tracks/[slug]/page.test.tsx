import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PathDetailPage from "./page";
import type { PathDetailResponse, RoomSummary } from "@/lib/api";

const getPathDetailMock = vi.fn();
vi.mock("@/lib/api", async () => ({
  getPathDetail: (...args: unknown[]) => getPathDetailMock(...args),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "python-fundamentals" }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.HTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// Stub the course store so we can drive `courses[0]` from each test
// case. Mirrors the selector-based pattern used by other components in
// the app (chat-input, search-dialog).
const courseStoreState: { courses: Array<{ id: string }>; fetchCourses: () => Promise<void> } = {
  courses: [],
  fetchCourses: vi.fn().mockResolvedValue(undefined),
};
vi.mock("@/store/course", () => ({
  useCourseStore: (selector: (s: typeof courseStoreState) => unknown) =>
    selector(courseStoreState),
}));

// Stub the CTA so its internal modal/state plumbing doesn't bleed into
// these page-level tests. We only care that the page mounts the CTA
// with the correct props in the right slot.
vi.mock("@/components/dashboard/generate-room-cta", () => ({
  GenerateRoomCTA: (props: {
    pathId: string;
    courseId: string;
    pathSlug: string;
    variant?: string;
  }) => (
    <div
      data-testid="generate-room-cta-stub"
      data-path-id={props.pathId}
      data-course-id={props.courseId}
      data-path-slug={props.pathSlug}
      data-variant={props.variant ?? "dashboard-rail"}
    />
  ),
}));

function makeRoom(overrides: Partial<RoomSummary> = {}): RoomSummary {
  return {
    id: "room-1",
    slug: "variables",
    title: "Variables and types",
    room_order: 1,
    task_total: 5,
    task_complete: 0,
    intro_excerpt: null,
    outcome: "Complete this mission",
    difficulty: 2,
    eta_minutes: 15,
    module_label: "",
    ...overrides,
  };
}

function makeDetail(rooms: RoomSummary[]): PathDetailResponse {
  return {
    id: "p1",
    slug: "python-fundamentals",
    title: "Python Fundamentals",
    difficulty: "beginner",
    track_id: "fundamentals",
    description: "Start here.",
    rooms,
    room_total: rooms.length,
    room_complete: rooms.filter(
      (r) => r.task_total > 0 && r.task_complete >= r.task_total,
    ).length,
  };
}

describe("/tracks/[slug] page", () => {
  beforeEach(() => {
    getPathDetailMock.mockReset();
    // Reset shared course-store state between tests.
    courseStoreState.courses = [];
  });

  it("renders the room list once getPathDetail resolves", async () => {
    getPathDetailMock.mockResolvedValue(
      makeDetail([
        makeRoom({ id: "room-1", title: "Room One" }),
        makeRoom({ id: "room-2", title: "Room Two", room_order: 2 }),
      ]),
    );
    render(<PathDetailPage />);

    await waitFor(() => {
      expect(screen.getByTestId("room-item-room-1")).toBeInTheDocument();
    });
    // Scope title lookups to the main column — V2 also surfaces the
    // current/next room titles in the rail, so a global `getByText`
    // would now match multiple nodes.
    const main = screen.getByTestId("path-detail-main");
    expect(main).toHaveTextContent("Room One");
    expect(main).toHaveTextContent("Room Two");
    expect(screen.getByTestId("path-detail-summary")).toHaveTextContent(
      "0/2 missions cleared",
    );
    // Call was made with the slug from useParams.
    expect(getPathDetailMock).toHaveBeenCalledWith("python-fundamentals");
  });

  it("lays out shell + main + rail with the expected testids and rail content", async () => {
    getPathDetailMock.mockResolvedValue(
      makeDetail([
        makeRoom({ id: "room-1", title: "Room One", task_total: 5 }),
        makeRoom({
          id: "room-2",
          title: "Room Two",
          room_order: 2,
          task_total: 3,
          task_complete: 3,
        }),
      ]),
    );
    render(<PathDetailPage />);

    // Outer shell is rendered immediately (wraps loading state too).
    expect(screen.getByTestId("path-detail-shell")).toBeInTheDocument();

    // Main + rail appear once data resolves.
    await waitFor(() => {
      expect(screen.getByTestId("path-detail-main")).toBeInTheDocument();
    });
    expect(screen.getByTestId("path-detail-rail")).toBeInTheDocument();

    // Main column owns the room list.
    expect(screen.getByTestId("path-detail-main")).toContainElement(
      screen.getByTestId("room-item-room-1"),
    );

    // Rail surfaces the existing summary fields: title, description,
    // mission count, task count, difficulty.
    const rail = screen.getByTestId("path-detail-rail");
    expect(rail).toContainElement(screen.getByTestId("path-detail-rail-title"));
    expect(screen.getByTestId("path-detail-rail-title")).toHaveTextContent(
      "Python Fundamentals",
    );
    expect(
      screen.getByTestId("path-detail-rail-description"),
    ).toHaveTextContent("Start here.");
    expect(screen.getByTestId("path-detail-rail-missions")).toHaveTextContent(
      "1/2",
    );
    expect(screen.getByTestId("path-detail-rail-tasks")).toHaveTextContent(
      "3/8",
    );
    expect(screen.getByTestId("path-detail-rail-difficulty")).toHaveTextContent(
      /beginner/i,
    );
  });

  describe("V2 — guided route states", () => {
    it("rail current-step reflects the active room and next-unlock reflects the first locked room", async () => {
      // done | active(in-progress) | locked → current=room-2, next=room-3.
      getPathDetailMock.mockResolvedValue(
        makeDetail([
          makeRoom({
            id: "room-1",
            title: "Room One",
            task_total: 4,
            task_complete: 4,
          }),
          makeRoom({
            id: "room-2",
            title: "Room Two",
            room_order: 2,
            task_total: 5,
            task_complete: 2,
          }),
          makeRoom({
            id: "room-3",
            title: "Room Three",
            room_order: 3,
            task_total: 3,
            task_complete: 0,
          }),
        ]),
      );
      render(<PathDetailPage />);

      await waitFor(() => {
        expect(
          screen.getByTestId("path-detail-rail-current-step"),
        ).toBeInTheDocument();
      });

      const current = screen.getByTestId("path-detail-rail-current-step");
      expect(current).toHaveTextContent(/current step/i);
      expect(current).toHaveTextContent("Room Two");

      const next = screen.getByTestId("path-detail-rail-next-unlock");
      expect(next).toHaveTextContent(/next unlocks/i);
      expect(next).toHaveTextContent("Room Three");

      const note = screen.getByTestId("path-detail-rail-route-note");
      // Operational copy: name what you're doing, name what unlocks next.
      expect(note).toHaveTextContent(/Room Two/);
      expect(note).toHaveTextContent(/Room Three/);
    });

    it("rail uses 'Ready to start' phrasing when there is no in-progress room", async () => {
      getPathDetailMock.mockResolvedValue(
        makeDetail([
          makeRoom({ id: "room-1", title: "Room One", task_total: 4 }),
          makeRoom({
            id: "room-2",
            title: "Room Two",
            room_order: 2,
            task_total: 4,
          }),
        ]),
      );
      render(<PathDetailPage />);

      await waitFor(() => {
        expect(
          screen.getByTestId("path-detail-rail-route-note"),
        ).toBeInTheDocument();
      });
      expect(
        screen.getByTestId("path-detail-rail-route-note"),
      ).toHaveTextContent(/Ready to start Room One/);
    });

    it("renders distinct chips per route state on the room rows", async () => {
      // First room done, second active, third locked. We assert at least
      // two distinct chips render so we know the parent is plumbing
      // routeState into RoomListItem rather than letting every row fall
      // back to the count-based heuristic.
      getPathDetailMock.mockResolvedValue(
        makeDetail([
          makeRoom({
            id: "room-1",
            title: "Room One",
            task_total: 4,
            task_complete: 4,
          }),
          makeRoom({
            id: "room-2",
            title: "Room Two",
            room_order: 2,
            task_total: 5,
            task_complete: 2,
          }),
          makeRoom({
            id: "room-3",
            title: "Room Three",
            room_order: 3,
            task_total: 3,
            task_complete: 0,
          }),
        ]),
      );
      render(<PathDetailPage />);

      await waitFor(() => {
        expect(screen.getByTestId("room-item-room-3")).toBeInTheDocument();
      });

      // Done chip on room-1.
      expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
        "data-route-state",
        "done",
      );
      expect(screen.getByTestId("room-item-check-room-1")).toHaveTextContent(
        /done/i,
      );

      // Active chip on room-2.
      expect(screen.getByTestId("room-item-room-2")).toHaveAttribute(
        "data-route-state",
        "active",
      );
      expect(screen.getByTestId("room-item-chip-room-2")).toHaveTextContent(
        /active/i,
      );

      // Locked chip + helper line on room-3.
      expect(screen.getByTestId("room-item-room-3")).toHaveAttribute(
        "data-route-state",
        "locked",
      );
      expect(screen.getByTestId("room-item-chip-room-3")).toHaveTextContent(
        /locked/i,
      );
      expect(
        screen.getByTestId("room-item-locked-helper-room-3"),
      ).toBeInTheDocument();
    });
  });

  // Phase 16b Bundle B v2 — track-header CTA mount.
  describe("Track-header GenerateRoomCTA", () => {
    it("mounts the CTA in the page header when path detail + a course are both available", async () => {
      // Seed a course in the shared store so the page resolves a courseId.
      courseStoreState.courses = [{ id: "course-7" }];
      getPathDetailMock.mockResolvedValue(
        makeDetail([makeRoom({ id: "room-1", title: "Room One" })]),
      );
      render(<PathDetailPage />);

      await waitFor(() => {
        expect(
          screen.getByTestId("track-detail-generate-room-slot"),
        ).toBeInTheDocument();
      });

      // Slot wraps the CTA stub with the right variant + path/course wiring.
      const cta = screen.getByTestId("generate-room-cta-stub");
      expect(cta).toHaveAttribute("data-variant", "track-header");
      expect(cta).toHaveAttribute("data-path-id", "p1");
      expect(cta).toHaveAttribute("data-course-id", "course-7");
      expect(cta).toHaveAttribute("data-path-slug", "python-fundamentals");

      // No-course fallback should NOT mount when a course is present.
      expect(
        screen.queryByTestId("generate-room-cta-hidden-no-course"),
      ).not.toBeInTheDocument();
    });

    it("renders the no-course skeleton instead of the CTA when courses[] is empty", async () => {
      courseStoreState.courses = [];
      getPathDetailMock.mockResolvedValue(
        makeDetail([makeRoom({ id: "room-1", title: "Room One" })]),
      );
      render(<PathDetailPage />);

      // Wait for path detail to resolve so we know the header has rendered.
      await waitFor(() => {
        expect(screen.getByTestId("path-detail-main")).toBeInTheDocument();
      });

      // Slot + CTA stub absent; placeholder testid present.
      expect(
        screen.queryByTestId("track-detail-generate-room-slot"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId("generate-room-cta-stub"),
      ).not.toBeInTheDocument();
      expect(
        screen.getByTestId("generate-room-cta-hidden-no-course"),
      ).toBeInTheDocument();
    });
  });
});
