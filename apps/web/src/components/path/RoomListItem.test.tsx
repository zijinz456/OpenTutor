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

  it("advertises the right data-state for the three progress tiers (count-based fallback)", () => {
    // Backwards-compat path: no `routeState` prop → infer from counts.
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

  describe("explicit route state", () => {
    it("renders a Done chip when routeState='done'", () => {
      render(
        <RoomListItem
          pathSlug="python"
          room={makeRoom({ task_total: 3, task_complete: 3 })}
          routeState="done"
        />,
      );
      const row = screen.getByTestId("room-item-room-1");
      expect(row).toHaveAttribute("data-route-state", "done");
      const chip = screen.getByTestId("room-item-check-room-1");
      expect(chip).toHaveTextContent(/done/i);
    });

    it("renders an Active chip with amber emphasis when routeState='active'", () => {
      render(
        <RoomListItem
          pathSlug="python"
          room={makeRoom({ task_total: 5, task_complete: 2 })}
          routeState="active"
        />,
      );
      const row = screen.getByTestId("room-item-room-1");
      expect(row).toHaveAttribute("data-route-state", "active");
      // Legacy data-state stays in sync for any older selector.
      expect(row).toHaveAttribute("data-state", "in_progress");
      const chip = screen.getByTestId("room-item-chip-room-1");
      expect(chip).toHaveTextContent(/active/i);
      expect(chip.className).toMatch(/amber/);
    });

    it("renders a 'Ready now' chip when routeState='ready'", () => {
      render(
        <RoomListItem
          pathSlug="python"
          room={makeRoom({ task_total: 5, task_complete: 0 })}
          routeState="ready"
        />,
      );
      const row = screen.getByTestId("room-item-room-1");
      expect(row).toHaveAttribute("data-route-state", "ready");
      const chip = screen.getByTestId("room-item-chip-room-1");
      expect(chip).toHaveTextContent(/ready now/i);
    });

    it("renders a Locked chip plus the helper line when routeState='locked'", () => {
      render(
        <RoomListItem
          pathSlug="python"
          room={makeRoom({ task_total: 5, task_complete: 0 })}
          routeState="locked"
        />,
      );
      const row = screen.getByTestId("room-item-room-1");
      expect(row).toHaveAttribute("data-route-state", "locked");
      const chip = screen.getByTestId("room-item-chip-room-1");
      expect(chip).toHaveTextContent(/locked/i);
      expect(
        screen.getByTestId("room-item-locked-helper-room-1"),
      ).toHaveTextContent(/locked until this mission is done/i);
    });

    it("explicit routeState overrides the count-based fallback", () => {
      // Counts say "done" (5/5) but parent forces ready — parent wins.
      render(
        <RoomListItem
          pathSlug="python"
          room={makeRoom({ task_total: 5, task_complete: 5 })}
          routeState="ready"
        />,
      );
      expect(screen.getByTestId("room-item-room-1")).toHaveAttribute(
        "data-route-state",
        "ready",
      );
      expect(
        screen.queryByTestId("room-item-check-room-1"),
      ).not.toBeInTheDocument();
    });
  });
});
