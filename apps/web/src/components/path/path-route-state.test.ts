import { describe, it, expect } from "vitest";
import {
  deriveRoomRouteStates,
  findActiveOrReadyRoom,
  findNextLockedRoom,
  type RoomLike,
} from "./path-route-state";

/** Compact factory for table-driven tests. We only ever exercise the
 *  three fields the helper actually reads (id + counts), keeping each
 *  case readable. */
function room(id: string, total: number, complete: number): RoomLike {
  return { id, task_total: total, task_complete: complete };
}

describe("deriveRoomRouteStates", () => {
  it("returns an empty list for no rooms", () => {
    expect(deriveRoomRouteStates([])).toEqual([]);
  });

  it("marks every fully-completed room as done", () => {
    const result = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 5, 5),
    ]);
    expect(result.map((r) => r.route_state)).toEqual(["done", "done"]);
  });

  it("treats the first non-done room with progress as active and the rest as locked", () => {
    const result = deriveRoomRouteStates([
      room("a", 3, 3), // done
      room("b", 5, 2), // active (first non-done with progress)
      room("c", 4, 0), // locked
      room("d", 4, 0), // locked
    ]);
    expect(result.map((r) => r.route_state)).toEqual([
      "done",
      "active",
      "locked",
      "locked",
    ]);
  });

  it("marks the first non-done room as ready when no room has progress yet", () => {
    const result = deriveRoomRouteStates([
      room("a", 3, 0),
      room("b", 4, 0),
      room("c", 5, 0),
    ]);
    expect(result.map((r) => r.route_state)).toEqual([
      "ready",
      "locked",
      "locked",
    ]);
  });

  it("handles the canonical mixed case: done | done | in-progress | not-started | not-started", () => {
    const result = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 4, 4),
      room("c", 5, 1),
      room("d", 4, 0),
      room("e", 4, 0),
    ]);
    expect(result.map((r) => r.route_state)).toEqual([
      "done",
      "done",
      "active",
      "locked",
      "locked",
    ]);
  });

  it("never produces more than one active or one ready room", () => {
    // Two rooms with progress — only the first becomes active; the
    // second is locked because the active slot is already filled.
    const result = deriveRoomRouteStates([
      room("a", 5, 2),
      room("b", 5, 3),
      room("c", 5, 0),
    ]);
    const active = result.filter((r) => r.route_state === "active");
    const ready = result.filter((r) => r.route_state === "ready");
    expect(active).toHaveLength(1);
    expect(active[0].id).toBe("a");
    expect(ready).toHaveLength(0);
    expect(result[1].route_state).toBe("locked");
  });

  it("prefers active over ready when one room has progress and another doesn't", () => {
    // First room has no progress, second has progress. The active rule
    // looks at the FIRST non-done with progress (room b), so the ready
    // rule never fires — room a stays locked.
    const result = deriveRoomRouteStates([
      room("a", 5, 0),
      room("b", 5, 2),
      room("c", 5, 0),
    ]);
    expect(result.map((r) => r.route_state)).toEqual([
      "locked",
      "active",
      "locked",
    ]);
  });

  it("does not mark a task_total=0 room as done; it falls through to ready/locked instead", () => {
    // Documented edge: zero-task rooms cannot satisfy `task_total > 0`,
    // so they stay non-done. With no progress anywhere, the first such
    // room becomes ready; later ones become locked.
    const result = deriveRoomRouteStates([
      room("a", 0, 0),
      room("b", 0, 0),
    ]);
    expect(result.map((r) => r.route_state)).toEqual(["ready", "locked"]);
  });
});

describe("findActiveOrReadyRoom", () => {
  it("returns the active room when one exists", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 5, 2),
      room("c", 4, 0),
    ]);
    expect(findActiveOrReadyRoom(states)?.id).toBe("b");
  });

  it("returns the ready room when no active room exists", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 0),
      room("b", 4, 0),
    ]);
    expect(findActiveOrReadyRoom(states)?.id).toBe("a");
  });

  it("returns null when every room is done", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 4, 4),
    ]);
    expect(findActiveOrReadyRoom(states)).toBeNull();
  });
});

describe("findNextLockedRoom", () => {
  it("returns the first locked room after the active room", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 5, 2), // active
      room("c", 4, 0), // locked  <- expected
      room("d", 4, 0), // locked
    ]);
    expect(findNextLockedRoom(states)?.id).toBe("c");
  });

  it("returns the first locked room after the ready room", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 0), // ready
      room("b", 4, 0), // locked  <- expected
      room("c", 4, 0), // locked
    ]);
    expect(findNextLockedRoom(states)?.id).toBe("b");
  });

  it("returns null when there is no active or ready room (all done)", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 4, 4),
    ]);
    expect(findNextLockedRoom(states)).toBeNull();
  });

  it("returns null when the only non-done room is the active one", () => {
    const states = deriveRoomRouteStates([
      room("a", 3, 3),
      room("b", 5, 2), // active, nothing locked after
    ]);
    expect(findNextLockedRoom(states)).toBeNull();
  });
});
