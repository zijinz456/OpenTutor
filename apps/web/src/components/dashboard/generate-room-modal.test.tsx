import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GenerateRoomModal } from "./generate-room-modal";

// --- Router mock --------------------------------------------------------
const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

// --- API + SSE hook mock -----------------------------------------------
//
// Subagent B owns these modules; we mock the symbols we use. The hook is
// a stateful spy: tests call `publishStream(...)` to drive transitions
// outside React's render cycle, then assertions are wrapped in `act` so
// the new state flushes before queries.
const generateRoomMock = vi.fn();

interface StreamState {
  status: string;
  progress: number;
  roomId: string | null;
  pathId: string | null;
  error: { code: string; message?: string } | null;
}

let streamListeners: Array<(s: StreamState) => void> = [];
let currentStream: StreamState | null = null;

const IDLE: StreamState = {
  status: "idle",
  progress: 0,
  roomId: null,
  pathId: null,
  error: null,
};

function publishStream(next: StreamState) {
  currentStream = next;
  streamListeners.forEach((fn) => fn(next));
}

vi.mock("@/lib/api/path-generation", () => ({
  generateRoom: (req: unknown) => generateRoomMock(req),
}));

vi.mock("@/hooks/use-room-generation-stream", async () => {
  const React = await import("react");
  return {
    useRoomGenerationStream: (jobId: string | null): StreamState => {
      const [s, setS] = React.useState<StreamState>(currentStream ?? IDLE);
      React.useEffect(() => {
        if (jobId === null) {
          setS(IDLE);
          return;
        }
        const fn = (next: StreamState) => setS(next);
        streamListeners.push(fn);
        // Sync to whatever the test has already published; default to a
        // fresh "queued" state mirroring the real hook on subscribe.
        setS(
          currentStream ?? {
            status: "queued",
            progress: 0,
            roomId: null,
            pathId: null,
            error: null,
          },
        );
        return () => {
          streamListeners = streamListeners.filter((f) => f !== fn);
        };
      }, [jobId]);
      return s;
    },
  };
});

// --- Helpers -----------------------------------------------------------

function renderModal(overrides: Partial<{
  pathId: string;
  courseId: string;
  pathSlug: string;
  isOpen: boolean;
  onClose: () => void;
}> = {}) {
  const props = {
    pathId: "path-1",
    courseId: "course-1",
    pathSlug: "python-bootcamp",
    isOpen: true,
    onClose: vi.fn(),
    ...overrides,
  };
  return { ...render(<GenerateRoomModal {...props} />), props };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockPush.mockReset();
  generateRoomMock.mockReset();
  streamListeners = [];
  currentStream = null;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("<GenerateRoomModal>", () => {
  it("renders the 3 form fields when open", () => {
    renderModal();
    expect(screen.getByTestId("generate-room-topic")).toBeInTheDocument();
    expect(screen.getByTestId("generate-room-difficulty")).toBeInTheDocument();
    expect(screen.getByTestId("generate-room-task-count")).toBeInTheDocument();
  });

  it("disables submit until topic length >= 3", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderModal();
    const submit = screen.getByTestId("generate-room-submit");
    expect(submit).toBeDisabled();

    const topic = screen.getByTestId("generate-room-topic");
    await user.type(topic, "Py");
    expect(submit).toBeDisabled();

    await user.type(topic, "thon decorators");
    expect(submit).not.toBeDisabled();
  });

  it("calls generateRoom with the trimmed payload on submit", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockResolvedValue({ job_id: "job-xyz", reused: false });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "  Python decorators  ",
    );
    await user.selectOptions(
      screen.getByTestId("generate-room-difficulty"),
      "intermediate",
    );
    await user.selectOptions(
      screen.getByTestId("generate-room-task-count"),
      "6",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    expect(generateRoomMock).toHaveBeenCalledTimes(1);
    expect(generateRoomMock).toHaveBeenCalledWith({
      path_id: "path-1",
      course_id: "course-1",
      topic: "Python decorators",
      difficulty: "intermediate",
      task_count: 6,
    });
  });

  it("on reused=true response navigates to /tracks/<slug>/missions/<room_id>", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockResolvedValue({
      reused: true,
      room_id: "room-42",
      path_id: "path-1",
    });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Python decorators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    await screen.findByTestId("generate-room-reused");

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(mockPush).toHaveBeenCalledWith(
      "/tracks/python-bootcamp/missions/room-42",
    );
  });

  it("on job_id response enters streaming and progresses to completion", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockResolvedValue({ job_id: "job-9", reused: false });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Async iterators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    // Stream UI is mounted (queued by default; the chip shows "Queued").
    await screen.findByTestId("generate-room-streaming");

    // outline → tasks → persisting → completed
    await act(async () => {
      publishStream({
        status: "outline",
        progress: 1,
        roomId: null,
        pathId: null,
        error: null,
      });
    });
    expect(screen.getByTestId("generate-room-status-chip")).toHaveTextContent(
      "Drafting outline",
    );

    await act(async () => {
      publishStream({
        status: "tasks",
        progress: 2,
        roomId: null,
        pathId: null,
        error: null,
      });
    });
    expect(screen.getByTestId("generate-room-status-chip")).toHaveTextContent(
      "Writing tasks",
    );

    await act(async () => {
      publishStream({
        status: "persisting",
        progress: 3,
        roomId: null,
        pathId: null,
        error: null,
      });
    });
    expect(screen.getByTestId("generate-room-status-chip")).toHaveTextContent(
      "Saving room",
    );

    await act(async () => {
      publishStream({
        status: "completed",
        progress: 4,
        roomId: "room-77",
        pathId: "path-1",
        error: null,
      });
    });

    await screen.findByTestId("generate-room-done");
    expect(screen.getByTestId("generate-room-done")).toHaveTextContent(
      "Room ready",
    );

    // v2 success-redirect window is 2s (was 600ms in v1).
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
    expect(mockPush).toHaveBeenCalledWith(
      "/tracks/python-bootcamp/missions/room-77",
    );
  });

  it("maps topic_guard rejection to friendly copy", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    // Simulate a 400 from the API client surfacing { detail: { error: "topic_guard" } }
    generateRoomMock.mockRejectedValue({
      detail: { error: "topic_guard" },
    });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Forbidden topic",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    await screen.findByTestId("generate-room-error");
    expect(screen.getByTestId("generate-room-error")).toHaveTextContent(
      "That topic was rejected. Rephrase and try again.",
    );
  });

  it("Esc during persisting is ignored; otherwise it closes", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();

    // Round 1 — Esc with no stream closes.
    const { rerender } = render(
      <GenerateRoomModal
        pathId="path-1"
        courseId="course-1"
        pathSlug="python-bootcamp"
        isOpen={true}
        onClose={onClose}
      />,
    );
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    // Round 2 — same modal, but stream is now persisting; Esc must be ignored.
    onClose.mockReset();
    // Pre-publish the persisting state, then submit so the modal subscribes.
    generateRoomMock.mockResolvedValue({ job_id: "job-1", reused: false });
    rerender(
      <GenerateRoomModal
        pathId="path-1"
        courseId="course-1"
        pathSlug="python-bootcamp"
        isOpen={true}
        onClose={onClose}
      />,
    );
    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Python decorators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));
    await screen.findByTestId("generate-room-streaming");

    await act(async () => {
      publishStream({
        status: "persisting",
        progress: 3,
        roomId: null,
        pathId: null,
        error: null,
      });
    });

    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("uses pathSlug (not pathId) in the navigation URL", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockResolvedValue({
      reused: true,
      room_id: "room-99",
      path_id: "path-1",
    });
    renderModal({ pathId: "path-1", pathSlug: "different-slug" });

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Python decorators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    await screen.findByTestId("generate-room-reused");
    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(mockPush).toHaveBeenCalledWith(
      "/tracks/different-slug/missions/room-99",
    );
    // And specifically NOT the path id.
    expect(mockPush).not.toHaveBeenCalledWith(
      expect.stringContaining("/tracks/path-1/"),
    );
  });

  // ── v2 polish (Phase 16b Bundle B v2) ────────────────────────────
  //
  // The block below covers the new 4-step progress visual, the amber
  // error block w/ retry, and the success block w/ View room / Stay
  // here controls. Existing tests above remain unchanged structurally.

  /**
   * Helper — drive the modal into the streaming phase quickly so we
   * can assert about progress rendering. Returns the user-event
   * instance for further interactions.
   */
  async function reachStreaming() {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockResolvedValue({ job_id: "job-x", reused: false });
    renderModal();
    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Async iterators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));
    await screen.findByTestId("generate-room-streaming");
    return user;
  }

  it("renders all 4 progress step rows with stable testids while streaming", async () => {
    await reachStreaming();
    // 4 rows present.
    for (let i = 0; i < 4; i += 1) {
      expect(
        screen.getByTestId(`generation-progress-step-${i}`),
      ).toBeInTheDocument();
    }
  });

  it("marks the current step per stream status (tasks → row 1 current, row 0 done)", async () => {
    await reachStreaming();

    await act(async () => {
      publishStream({
        status: "tasks",
        progress: 2,
        roomId: null,
        pathId: null,
        error: null,
      });
    });

    expect(
      screen.getByTestId("generation-progress-step-0"),
    ).toHaveAttribute("data-step-state", "done");
    expect(
      screen.getByTestId("generation-progress-step-1"),
    ).toHaveAttribute("data-step-state", "current");
    expect(
      screen.getByTestId("generation-progress-step-2"),
    ).toHaveAttribute("data-step-state", "pending");
    expect(
      screen.getByTestId("generation-progress-step-3"),
    ).toHaveAttribute("data-step-state", "pending");
  });

  it("on persisting status: rows 0–1 done, row 2 current, row 3 pending", async () => {
    await reachStreaming();

    await act(async () => {
      publishStream({
        status: "persisting",
        progress: 3,
        roomId: null,
        pathId: null,
        error: null,
      });
    });

    expect(
      screen.getByTestId("generation-progress-step-0"),
    ).toHaveAttribute("data-step-state", "done");
    expect(
      screen.getByTestId("generation-progress-step-1"),
    ).toHaveAttribute("data-step-state", "done");
    expect(
      screen.getByTestId("generation-progress-step-2"),
    ).toHaveAttribute("data-step-state", "current");
    expect(
      screen.getByTestId("generation-progress-step-3"),
    ).toHaveAttribute("data-step-state", "pending");
  });

  it("retryable error (topic_guard) shows Try again; clicking it returns to form preserving inputs", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockRejectedValue({
      detail: { error: "topic_guard" },
    });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Forbidden topic",
    );
    await user.selectOptions(
      screen.getByTestId("generate-room-difficulty"),
      "advanced",
    );
    await user.selectOptions(
      screen.getByTestId("generate-room-task-count"),
      "7",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    // Error block is visible with the amber container + retry CTA.
    await screen.findByTestId("generation-error-block");
    expect(
      screen.getByTestId("generation-error-retry"),
    ).toBeInTheDocument();

    // Click Retry → back to the form, prior inputs preserved.
    await user.click(screen.getByTestId("generation-error-retry"));

    expect(screen.getByTestId("generate-room-form")).toBeInTheDocument();
    expect(screen.getByTestId("generate-room-topic")).toHaveValue(
      "Forbidden topic",
    );
    expect(screen.getByTestId("generate-room-difficulty")).toHaveValue(
      "advanced",
    );
    expect(screen.getByTestId("generate-room-task-count")).toHaveValue("7");
    // No error block lingering.
    expect(
      screen.queryByTestId("generation-error-block"),
    ).not.toBeInTheDocument();
  });

  it("non-retryable error (daily_generation_cap_exceeded) hides the Retry button", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockRejectedValue({
      detail: { error: "daily_generation_cap_exceeded" },
    });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Python decorators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    await screen.findByTestId("generation-error-block");
    expect(
      screen.queryByTestId("generation-error-retry"),
    ).not.toBeInTheDocument();
    // Close is still available.
    expect(
      screen.getByTestId("generate-room-error-close"),
    ).toBeInTheDocument();
  });

  it("non-retryable error (path_course_mismatch) hides the Retry button", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    generateRoomMock.mockRejectedValue({
      detail: { error: "path_course_mismatch" },
    });
    renderModal();

    await user.type(
      screen.getByTestId("generate-room-topic"),
      "Python decorators",
    );
    await user.click(screen.getByTestId("generate-room-submit"));

    await screen.findByTestId("generation-error-block");
    expect(
      screen.queryByTestId("generation-error-retry"),
    ).not.toBeInTheDocument();
  });

  it("success state shows Room ready + View room + Stay here", async () => {
    const user = await reachStreaming();
    await act(async () => {
      publishStream({
        status: "completed",
        progress: 4,
        roomId: "room-success",
        pathId: "path-1",
        error: null,
      });
    });

    await screen.findByTestId("generation-success-block");
    expect(screen.getByTestId("generation-success-block")).toHaveTextContent(
      "Room ready",
    );
    expect(screen.getByTestId("generation-success-block")).toHaveTextContent(
      "Opening it in 2 seconds",
    );
    expect(
      screen.getByTestId("generation-success-view"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("generation-success-stay"),
    ).toBeInTheDocument();
    // Side note: the user-event instance is unused but reachStreaming
    // returns it for symmetry — silence the lint via reference.
    expect(typeof user.click).toBe("function");
  });

  it("clicking Stay here cancels the auto-redirect", async () => {
    const user = await reachStreaming();
    await act(async () => {
      publishStream({
        status: "completed",
        progress: 4,
        roomId: "room-stay",
        pathId: "path-1",
        error: null,
      });
    });

    await screen.findByTestId("generation-success-block");
    await user.click(screen.getByTestId("generation-success-stay"));

    // Even after the 2s window elapses, no push() should fire.
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(mockPush).not.toHaveBeenCalled();
    // Success block is still visible — user can dismiss manually.
    expect(
      screen.getByTestId("generation-success-block"),
    ).toBeInTheDocument();
  });

  it("clicking View room redirects immediately (not waiting for the 2s window)", async () => {
    const user = await reachStreaming();
    await act(async () => {
      publishStream({
        status: "completed",
        progress: 4,
        roomId: "room-view",
        pathId: "path-1",
        error: null,
      });
    });

    await screen.findByTestId("generation-success-block");
    await user.click(screen.getByTestId("generation-success-view"));

    // Pushed synchronously on click — no timer advance needed.
    expect(mockPush).toHaveBeenCalledWith(
      "/tracks/python-bootcamp/missions/room-view",
    );
    // And only once: the auto-redirect must not also fire.
    const callsAfterClick = mockPush.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(mockPush.mock.calls.length).toBe(callsAfterClick);
  });
});
