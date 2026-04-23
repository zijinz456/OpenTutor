/**
 * Unit tests for <ScreenshotDropZone> (Phase 4 T4c).
 *
 * We mock `globalThis.fetch` and let the real component-to-api path run —
 * that way a regression in `lib/api/screenshot.ts` surfaces here too.
 *
 * Notable mocks:
 *   - `URL.createObjectURL` / `revokeObjectURL` — jsdom ≥22 provides
 *     these but we neutralise them so we don't leak blob-URLs between
 *     tests.
 *   - `Image` — jsdom's default never fires `load`. We patch
 *     `HTMLImageElement`'s `src` setter to resolve synchronously with
 *     test-configurable `naturalWidth/Height`.
 *   - `HTMLCanvasElement.toBlob` — jsdom returns null by default; we
 *     stub it so the downsample path can produce a real Blob.
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
import { ScreenshotDropZone } from "./ScreenshotDropZone";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// jsdom's `URL.createObjectURL` may or may not exist depending on version.
// Stub to a stable string so the component's revoke call is a no-op.
Object.defineProperty(globalThis.URL, "createObjectURL", {
  value: () => "blob:mock",
  writable: true,
});
Object.defineProperty(globalThis.URL, "revokeObjectURL", {
  value: () => undefined,
  writable: true,
});

/** Controls the `naturalWidth/Height` our patched Image reports. */
let mockImageSize = { w: 800, h: 600 };

// jsdom never fires `onload` on `Image`. Patch the `src` setter so setting
// it synchronously calls `onload` after we've written the configured
// dimensions onto the instance.
Object.defineProperty(HTMLImageElement.prototype, "src", {
  configurable: true,
  set(this: HTMLImageElement) {
    Object.defineProperty(this, "naturalWidth", {
      configurable: true,
      value: mockImageSize.w,
    });
    Object.defineProperty(this, "naturalHeight", {
      configurable: true,
      value: mockImageSize.h,
    });
    // Defer to microtask so the awaiting promise in the component has
    // its handler attached by the time we invoke it.
    queueMicrotask(() => {
      this.onload?.(new Event("load"));
    });
  },
  get() {
    return "blob:mock";
  },
});

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeImage(
  name = "shot.png",
  mime = "image/png",
  size = 200 * 1024,
): File {
  const blob = new Blob([new Uint8Array(size)], { type: mime });
  return new File([blob], name, { type: mime });
}

/** Simulate a drag-drop of `file` onto the dropzone target. */
function dropFile(target: HTMLElement, file: File) {
  const dataTransfer = {
    files: [file],
    items: [{ kind: "file", type: file.type, getAsFile: () => file }],
    types: ["Files"],
  } as unknown as DataTransfer;
  fireEvent.drop(target, { dataTransfer });
}

const UPLOAD_OK = {
  candidates: [
    {
      front: "What does the ternary operator return?",
      back: "The first operand if the condition is truthy, else the second.",
      concept_slug: "ternary-operator",
      screenshot_hash: "a3f9b1c2d4e5f678",
    },
    {
      front: "Why does `==` fail for {} == {}?",
      back: "Object identity, not structural equality.",
      concept_slug: "equality",
      screenshot_hash: "a3f9b1c2d4e5f678",
    },
    {
      front: "What is hoisting?",
      back: "Declarations are moved to the top of their scope at parse time.",
      concept_slug: "hoisting",
      screenshot_hash: "a3f9b1c2d4e5f678",
    },
  ],
  screenshot_hash: "a3f9b1c2d4e5f678",
  vision_latency_ms: 14230,
  ungrounded_dropped_count: 0,
};

describe("ScreenshotDropZone", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockImageSize = { w: 800, h: 600 };
    localStorage.clear();
  });

  afterEach(() => {
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("renders drop zone with image MIME accept filter", () => {
    render(<ScreenshotDropZone courseId="course-1" />);
    expect(screen.getByTestId("screenshot-drop-zone")).toBeInTheDocument();
    const input = screen.getByTestId("screenshot-file-input") as HTMLInputElement;
    expect(input.getAttribute("accept")).toBe(
      "image/png,image/jpeg,image/webp",
    );
    expect(input.type).toBe("file");
    // Privacy subtitle visible in idle state.
    const subtitle = screen.getByTestId("screenshot-privacy-subtitle");
    expect(subtitle.textContent?.toLowerCase()).toContain(
      "vision reads everything",
    );
  });

  it("drop PNG -> uploads via fetch to /upload/screenshot", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(UPLOAD_OK));
    render(<ScreenshotDropZone courseId="course-1" />);
    const target = screen.getByTestId("screenshot-dropzone-target");
    const file = makeImage("shot.png", "image/png", 200 * 1024);
    await act(async () => {
      dropFile(target, file);
    });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/content/upload/screenshot");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    expect(form.get("course_id")).toBe("course-1");
    expect(form.get("file")).toBeInstanceOf(File);
  });

  it("large image downsampled before upload", async () => {
    mockImageSize = { w: 4000, h: 3000 };
    mockFetch.mockResolvedValueOnce(jsonResponse(UPLOAD_OK));

    // jsdom doesn't implement `getContext("2d")`; stub a no-op-ish 2D
    // context so the downsample path proceeds to `toBlob`.
    const fakeCtx = { drawImage: () => undefined } as unknown as CanvasRenderingContext2D;
    const getCtxSpy = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(fakeCtx as unknown as RenderingContext);

    // Stub `HTMLCanvasElement.toBlob` to produce a real Blob so the
    // component doesn't fall back to the original File.
    const toBlobSpy = vi
      .spyOn(HTMLCanvasElement.prototype, "toBlob")
      .mockImplementation(function (
        this: HTMLCanvasElement,
        callback: BlobCallback,
        type?: string,
      ) {
        callback(new Blob([new Uint8Array(10 * 1024)], { type: type ?? "image/jpeg" }));
      });

    render(<ScreenshotDropZone courseId="course-1" />);
    await act(async () => {
      dropFile(
        screen.getByTestId("screenshot-dropzone-target"),
        makeImage("huge.png", "image/png", 5 * 1024 * 1024),
      );
    });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(toBlobSpy).toHaveBeenCalled();
    toBlobSpy.mockRestore();
    getCtxSpy.mockRestore();
  });

  it("preview shows 3 cards after successful upload", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(UPLOAD_OK));
    render(<ScreenshotDropZone courseId="course-1" />);
    await act(async () => {
      dropFile(
        screen.getByTestId("screenshot-dropzone-target"),
        makeImage(),
      );
    });
    const preview = await screen.findByTestId("screenshot-preview");
    expect(preview).toBeInTheDocument();
    expect(screen.getByTestId("screenshot-candidate-0-front").textContent).toContain(
      "ternary operator",
    );
    expect(screen.getByTestId("screenshot-candidate-1-front").textContent).toContain(
      "`==` fail",
    );
    expect(screen.getByTestId("screenshot-candidate-2-front").textContent).toContain(
      "hoisting",
    );
    expect(screen.getByTestId("screenshot-save-all").textContent).toContain(
      "Save all 3 cards",
    );
  });

  it("Save all -> POST to save-candidates with spawn_origin screenshot", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse(UPLOAD_OK))
      .mockResolvedValueOnce(
        jsonResponse({
          saved_problem_ids: ["pp-1", "pp-2", "pp-3"],
          asset_id: "asset-1",
          count: 3,
          warnings: [],
        }),
      );
    render(<ScreenshotDropZone courseId="course-1" />);
    await act(async () => {
      dropFile(
        screen.getByTestId("screenshot-dropzone-target"),
        makeImage(),
      );
    });
    await screen.findByTestId("screenshot-save-all");
    await act(async () => {
      fireEvent.click(screen.getByTestId("screenshot-save-all"));
    });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));

    const [url, init] = mockFetch.mock.calls[1] as [string, RequestInit];
    expect(url).toContain("/courses/course-1/flashcards/save-candidates");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string) as {
      candidates: Array<Record<string, unknown>>;
      spawn_origin: string;
    };
    expect(body.spawn_origin).toBe("screenshot");
    expect(body.candidates).toHaveLength(3);
    for (const c of body.candidates) {
      expect(c.screenshot_hash).toBe("a3f9b1c2d4e5f678");
    }

    const saved = await screen.findByTestId("screenshot-saved");
    expect(saved.textContent).toContain("Saved 3 cards");
    expect(
      screen.getByTestId("screenshot-saved-link").getAttribute("href"),
    ).toBe("/flashcards/due/course-1");
  });

  it("413 size error renders hint", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Screenshot too large" }, 413),
    );
    render(<ScreenshotDropZone courseId="course-1" />);
    await act(async () => {
      dropFile(
        screen.getByTestId("screenshot-dropzone-target"),
        makeImage(),
      );
    });
    const err = await screen.findByTestId("screenshot-error");
    expect(err).toBeInTheDocument();
    expect(
      screen.getByTestId("screenshot-error-detail").textContent,
    ).toContain("Screenshot too large");
    expect(
      screen.getByTestId("screenshot-error-hint").textContent,
    ).toContain("Downsample");
  });

  it("429 rate limit error renders cooldown", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Rate limit exceeded" }, 429),
    );
    render(<ScreenshotDropZone courseId="course-1" />);
    await act(async () => {
      dropFile(
        screen.getByTestId("screenshot-dropzone-target"),
        makeImage(),
      );
    });
    const err = await screen.findByTestId("screenshot-error");
    expect(err).toBeInTheDocument();
    const detailText = screen
      .getByTestId("screenshot-error-detail")
      .textContent?.toLowerCase();
    expect(detailText).toContain("too fast");
    const hintText = screen
      .getByTestId("screenshot-error-hint")
      .textContent?.toLowerCase();
    expect(hintText).toContain("5 screenshots per minute");
  });
});
