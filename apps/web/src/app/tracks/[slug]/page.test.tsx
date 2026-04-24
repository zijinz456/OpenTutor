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
    expect(screen.getByText("Room One")).toBeInTheDocument();
    expect(screen.getByText("Room Two")).toBeInTheDocument();
    expect(screen.getByTestId("path-detail-summary")).toHaveTextContent(
      "0/2 missions cleared",
    );
    // Call was made with the slug from useParams.
    expect(getPathDetailMock).toHaveBeenCalledWith("python-fundamentals");
  });
});
