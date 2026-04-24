import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RoomListItem } from "./RoomListItem";
import type { RoomSummary } from "@/lib/api";

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
    slug: "variables-and-types",
    title: "Variables and types",
    room_order: 1,
    task_total: 5,
    task_complete: 0,
    intro_excerpt: "Learn how Python tracks names and values.",
    outcome: "Complete this mission",
    difficulty: 2,
    eta_minutes: 15,
    module_label: "",
    ...overrides,
  };
}

describe("<RoomListItem>", () => {
  it("renders title and task counter", () => {
    render(<RoomListItem pathSlug="python" room={makeRoom()} />);
    expect(screen.getByText("Variables and types")).toBeInTheDocument();
    expect(screen.getByTestId("room-item-progress-room-1")).toHaveTextContent(
      "0/5",
    );
    expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
      "href",
      "/tracks/python/missions/room-1",
    );
  });

  it("shows the done badge when every task is complete", () => {
    render(
      <RoomListItem
        pathSlug="python"
        room={makeRoom({ task_total: 3, task_complete: 3 })}
      />,
    );
    expect(screen.getByTestId("room-item-check-room-1")).toBeInTheDocument();
    expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
      "data-state",
      "complete",
    );
  });

  it("advertises the right data-state for the three progress tiers", () => {
    const { rerender } = render(
      <RoomListItem
        pathSlug="python"
        room={makeRoom({ task_total: 5, task_complete: 0 })}
      />,
    );
    expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
      "data-state",
      "idle",
    );

    rerender(
      <RoomListItem
        pathSlug="python"
        room={makeRoom({ task_total: 5, task_complete: 2 })}
      />,
    );
    expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
      "data-state",
      "in_progress",
    );

    rerender(
      <RoomListItem
        pathSlug="python"
        room={makeRoom({ task_total: 5, task_complete: 5 })}
      />,
    );
    expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
      "data-state",
      "complete",
    );
  });
});
