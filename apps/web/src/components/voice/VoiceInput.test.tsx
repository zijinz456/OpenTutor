/**
 * Unit tests for <VoiceInput> (Phase 8 T3).
 *
 * MediaRecorder + getUserMedia are mocked — we drive recorder state
 * transitions by calling the fake recorder's `.stop()` and `ondataavailable`
 * handlers directly. Real mic capture is out of scope for unit tests.
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { VoiceInput } from "./VoiceInput";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Latest fake recorder instance — tests reach into it to simulate events. */
interface FakeRecorder {
  state: "inactive" | "recording" | "paused";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

let lastRecorder: FakeRecorder | null = null;

class FakeMediaRecorder {
  state: "inactive" | "recording" | "paused" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  start = vi.fn(() => {
    this.state = "recording";
  });

  stop = vi.fn(() => {
    this.state = "inactive";
    // Feed one chunk then fire onstop — mirrors real browser behaviour
    // (ondataavailable fires once on stop if `timeslice` wasn't passed).
    this.ondataavailable?.({
      data: new Blob([new Uint8Array(32)], { type: this.mimeType }),
    });
    this.onstop?.();
  });

  constructor(_stream: MediaStream, opts: { mimeType: string }) {
    this.mimeType = opts.mimeType;
    lastRecorder = this as unknown as FakeRecorder;
  }

  static isTypeSupported(_mime: string) {
    return true;
  }
}

// Stub getUserMedia to a fake MediaStream with one track we can stop.
function fakeMediaStream(): MediaStream {
  const track = {
    stop: vi.fn(),
    kind: "audio",
  };
  return {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream;
}

const getUserMediaMock = vi.fn(async () => fakeMediaStream());

describe("<VoiceInput>", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    lastRecorder = null;
    getUserMediaMock.mockClear();

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: getUserMediaMock },
    });
    vi.stubGlobal(
      "MediaRecorder",
      FakeMediaRecorder as unknown as typeof MediaRecorder,
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders mic button in idle state", () => {
    render(<VoiceInput onTranscribed={() => undefined} />);
    const root = screen.getByTestId("voice-input");
    expect(root.getAttribute("data-phase")).toBe("idle");
    expect(screen.getByTestId("voice-input-start")).toBeInTheDocument();
  });

  it("click start begins recording + shows countdown", async () => {
    render(<VoiceInput onTranscribed={() => undefined} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("voice-input-start"));
    });
    // getUserMedia + recorder.start should have fired.
    expect(getUserMediaMock).toHaveBeenCalledTimes(1);
    expect(lastRecorder?.start).toHaveBeenCalledTimes(1);
    // Countdown visible + stop button available.
    expect(screen.getByTestId("voice-input-countdown")).toBeInTheDocument();
    expect(screen.getByTestId("voice-input-stop")).toBeInTheDocument();
    expect(screen.getByTestId("voice-input").getAttribute("data-phase")).toBe(
      "recording",
    );
  });

  it("auto-stops at maxDurationSec timeout", async () => {
    vi.useFakeTimers();
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ text: "ok", language: "en", duration_ms: 60000 }),
    );
    render(
      <VoiceInput onTranscribed={() => undefined} maxDurationSec={5} />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("voice-input-start"));
    });
    // Advance past the hard cap — auto-stop should trigger recorder.stop().
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(lastRecorder?.stop).toHaveBeenCalledTimes(1);
  });

  it("onTranscribed called with API text after successful upload", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        text: "the distributed consistency trade-off is",
        language: "en",
        duration_ms: 4200,
      }),
    );
    const onTranscribed = vi.fn();
    render(
      <VoiceInput onTranscribed={onTranscribed} language="en" />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("voice-input-start"));
    });
    // User hits stop → recorder.stop() fires onstop → upload starts.
    await act(async () => {
      fireEvent.click(screen.getByTestId("voice-input-stop"));
    });
    await waitFor(() => expect(onTranscribed).toHaveBeenCalledTimes(1));
    expect(onTranscribed).toHaveBeenCalledWith(
      "the distributed consistency trade-off is",
    );
    // Returned to idle after emission.
    await waitFor(() =>
      expect(
        screen.getByTestId("voice-input").getAttribute("data-phase"),
      ).toBe("idle"),
    );
  });

  it("shows error state on 415 response", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Unsupported audio format" }, 415),
    );
    render(<VoiceInput onTranscribed={() => undefined} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("voice-input-start"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("voice-input-stop"));
    });
    const err = await screen.findByTestId("voice-input-error");
    expect(err).toBeInTheDocument();
    expect(
      screen.getByTestId("voice-input-error-detail").textContent,
    ).toContain("Unsupported audio format");
    // Next render should show the mic button again so the user can retry.
    expect(screen.getByTestId("voice-input-start")).toBeInTheDocument();
  });
});
