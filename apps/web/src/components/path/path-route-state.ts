/**
 * Pure helper for deriving room route states on a track-detail screen
 * (Visual Shell V2, Part D).
 *
 * Why this lives here
 * -------------------
 * The backend returns rooms with raw `task_total` / `task_complete` counts
 * but does not yet model "active vs ready vs locked" semantics. Visual
 * Shell V2 needs that distinction in the UI to make progression legible
 * without inventing new backend fields. This module is the single seam
 * where that derivation happens, so the page component and any rail/cards
 * consume the same labels.
 *
 * Rules (spec D.3)
 * ----------------
 *   done   — task_total > 0 AND task_complete >= task_total
 *   active — first non-done room with task_complete > 0 (resume here)
 *   ready  — if no active room exists, the first non-done room
 *   locked — every other non-done room
 *
 * Constraints (spec D.4)
 * ----------------------
 *   - At most one `active` room.
 *   - At most one `ready` room.
 *   - When both could fire on the same room (it has progress), `active`
 *     wins by definition because the rule fires first.
 *
 * Edge case: `task_total === 0`
 * -----------------------------
 *   A room with no tasks cannot be `done` (the rule requires a positive
 *   total). It is therefore eligible to become `active` (if it has
 *   progress, which is impossible without tasks) or `ready` (if first
 *   non-done) or `locked`. In practice with `task_total === 0` and
 *   `task_complete === 0`, it behaves like a normal not-started room and
 *   becomes `ready` if first, `locked` otherwise. We do NOT silently
 *   classify zero-task rooms as `done`, because that would let an empty
 *   placeholder mission look like the learner had cleared real work.
 */

export type RoomRouteState = "done" | "active" | "ready" | "locked";

export type RoomLike = {
  id: string;
  task_total: number;
  task_complete: number;
};

export type RoomWithRouteState<T extends RoomLike> = T & {
  route_state: RoomRouteState;
};

/** Apply spec D.3 rules to a list of rooms in their natural order.
 *  Returns the same rooms with a `route_state` tag attached. The input
 *  order is preserved — caller is responsible for sorting by `room_order`
 *  before invoking this if their data isn't already ordered. */
export function deriveRoomRouteStates<T extends RoomLike>(
  rooms: T[],
): RoomWithRouteState<T>[] {
  // Pass 1: figure out which rooms are done. We need this set to find the
  // "first non-done with progress" / "first non-done" without a second
  // mutable scan over the same array.
  const isDone = rooms.map(
    (r) => r.task_total > 0 && r.task_complete >= r.task_total,
  );

  // Pass 2: locate the first non-done room with progress (active). If no
  // such room exists, the first non-done room is `ready`. Everything else
  // non-done is `locked`. We deliberately resolve `active` before `ready`
  // so the at-most-one-of-each constraint is automatic.
  let activeIndex = -1;
  for (let i = 0; i < rooms.length; i++) {
    if (!isDone[i] && rooms[i].task_complete > 0) {
      activeIndex = i;
      break;
    }
  }

  let readyIndex = -1;
  if (activeIndex === -1) {
    for (let i = 0; i < rooms.length; i++) {
      if (!isDone[i]) {
        readyIndex = i;
        break;
      }
    }
  }

  return rooms.map((room, i) => {
    let state: RoomRouteState;
    if (isDone[i]) state = "done";
    else if (i === activeIndex) state = "active";
    else if (i === readyIndex) state = "ready";
    else state = "locked";
    return { ...room, route_state: state };
  });
}

/** Return the active room if one exists, otherwise the ready room, else
 *  null. Used by the rail to show "Current step". */
export function findActiveOrReadyRoom<T extends RoomLike>(
  states: RoomWithRouteState<T>[],
): RoomWithRouteState<T> | null {
  const active = states.find((r) => r.route_state === "active");
  if (active) return active;
  const ready = states.find((r) => r.route_state === "ready");
  return ready ?? null;
}

/** Return the first locked room AFTER the active/ready room. Used by the
 *  rail to show "Next unlocks". Falls back to null when nothing is
 *  locked or when there is no active/ready anchor (e.g. all rooms done). */
export function findNextLockedRoom<T extends RoomLike>(
  states: RoomWithRouteState<T>[],
): RoomWithRouteState<T> | null {
  const anchorIndex = states.findIndex(
    (r) => r.route_state === "active" || r.route_state === "ready",
  );
  if (anchorIndex === -1) return null;
  for (let i = anchorIndex + 1; i < states.length; i++) {
    if (states[i].route_state === "locked") return states[i];
  }
  return null;
}
