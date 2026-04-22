/**
 * Unit tests for <CourseraDropZone> (Phase 14 T7).
 *
 * We mock `globalThis.fetch` and let the real component-to-api path run —
 * that way a regression in `coursera.ts` surfaces here too.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { CourseraDropZone } from "./CourseraDropZone";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeZip(name = "coursera-course.zip", size = 5 * 1024 * 1024): File {
  // Construct a File with the requested `size` so the preview can show MB.
  // Blob content is irrelevant — server-side logic is mocked.
  const blob = new Blob([new Uint8Array(size)], { type: "application/zip" });
  return new File([blob], name, { type: "application/zip" });
}

/** Simulate a drag-drop of `file` onto the dropzone target. */
function dropFile(target: HTMLElement, file: File) {
  const dataTransfer = {
    files: [file],
    items: [
      { kind: "file", type: file.type, getAsFile: () => file },
    ],
    types: ["Files"],
  } as unknown as DataTransfer;
  fireEvent.drop(target, { dataTransfer });
}

describe("CourseraDropZone", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("renders drop zone, file input accepts only .zip", () => {
    render(<CourseraDropZone courseId="course-1" />);
    expect(screen.getByTestId("coursera-dropzone-target")).toBeInTheDocument();
    const input = screen.getByTestId("coursera-file-input") as HTMLInputElement;
    expect(input.getAttribute("accept")).toContain(".zip");
    expect(input.type).toBe("file");
  });

  it("drops file -> preview shows filename and size", () => {
    render(<CourseraDropZone courseId="course-1" />);
    const target = screen.getByTestId("coursera-dropzone-target");
    const file = makeZip("dl-ai-langchain.zip", 42 * 1024 * 1024);
    act(() => {
      dropFile(target, file);
    });
    expect(screen.getByTestId("coursera-preview-name").textContent).toBe(
      "dl-ai-langchain.zip",
    );
    // 42 MB — two-digit values render without decimal.
    expect(screen.getByTestId("coursera-preview-size").textContent).toBe("42 MB");
  });

  it("clicks import -> POSTs to /api/content/upload/coursera", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        course_id: "course-1",
        lectures_total: 3,
        lectures_paired: 2,
        lectures_vtt_only: 1,
        lectures_pdf_only: 0,
        job_ids: ["j1", "j2", "j3"],
        status: "created",
      }),
    );
    render(<CourseraDropZone courseId="course-1" />);
    act(() => {
      dropFile(screen.getByTestId("coursera-dropzone-target"), makeZip());
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("coursera-import"));
    });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/content/upload/coursera");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    expect(form.get("course_id")).toBe("course-1");
    expect(form.get("file")).toBeInstanceOf(File);
  });

  it("success response renders summary", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        course_id: "course-abc",
        lectures_total: 5,
        lectures_paired: 3,
        lectures_vtt_only: 1,
        lectures_pdf_only: 1,
        job_ids: ["j1", "j2", "j3", "j4", "j5"],
        status: "created",
      }),
    );
    render(<CourseraDropZone courseId="course-abc" />);
    act(() => {
      dropFile(screen.getByTestId("coursera-dropzone-target"), makeZip());
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("coursera-import"));
    });
    const success = await screen.findByTestId("coursera-success");
    expect(success.textContent).toContain("Imported 5 lectures");
    expect(success.textContent).toContain("3 paired");
    expect(screen.getByTestId("coursera-view-roadmap").getAttribute("href")).toBe(
      "/course/course-abc",
    );
  });

  it("already_imported response renders hint", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        course_id: "course-1",
        lectures_total: 7,
        lectures_paired: 6,
        lectures_vtt_only: 1,
        lectures_pdf_only: 0,
        job_ids: [],
        status: "already_imported",
      }),
    );
    render(<CourseraDropZone courseId="course-1" />);
    act(() => {
      dropFile(screen.getByTestId("coursera-dropzone-target"), makeZip());
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("coursera-import"));
    });
    const already = await screen.findByTestId("coursera-already");
    expect(already.textContent?.toLowerCase()).toContain("already imported");
    expect(already.textContent).toContain("7 lectures");
  });

  it("error response renders detail + hint", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: "Coursera ZIP rejected: path traversal detected. Hint: Check archive for '../' paths.",
        },
        400,
      ),
    );
    render(<CourseraDropZone courseId="course-1" />);
    act(() => {
      dropFile(screen.getByTestId("coursera-dropzone-target"), makeZip());
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("coursera-import"));
    });
    const errBox = await screen.findByTestId("coursera-error");
    expect(errBox).toBeInTheDocument();
    expect(screen.getByTestId("coursera-error-detail").textContent).toContain(
      "path traversal detected",
    );
    expect(screen.getByTestId("coursera-error-hint").textContent).toContain(
      "Check archive",
    );
  });
});
