/**
 * Unit tests for <UrlRecursivePopover> (§14.5 v2.5 T6).
 *
 * We mock `globalThis.fetch` and let the real component → api-client path
 * run — that way a regression in `url_recursive.ts` surfaces here too.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { UrlRecursivePopover } from "./UrlRecursivePopover";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("UrlRecursivePopover", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("renders URL, depth, and path-prefix inputs", () => {
    render(<UrlRecursivePopover courseId="course-1" />);

    expect(screen.getByTestId("url-recursive-url-input")).toBeInTheDocument();
    expect(screen.getByTestId("url-recursive-depth-input")).toBeInTheDocument();
    expect(
      screen.getByTestId("url-recursive-path-prefix-input"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("url-recursive-submit")).toBeInTheDocument();

    // Default depth = 2 per plan.
    expect(screen.getByTestId("url-recursive-depth-value").textContent).toBe(
      "2",
    );
  });

  it("submits to /api/content/upload/url/recursive with correct body", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        course_id: "course-1",
        pages_crawled: 4,
        pages_skipped_robots: 0,
        pages_skipped_origin: 1,
        pages_skipped_dedup: 0,
        pages_fetch_failed: 0,
        job_ids: ["j1", "j2", "j3", "j4"],
      }),
    );

    render(<UrlRecursivePopover courseId="course-1" />);

    // Fill the URL + path-prefix; nudge depth to 3 to verify it propagates.
    fireEvent.change(screen.getByTestId("url-recursive-url-input"), {
      target: { value: "https://docs.python.org/3/tutorial/" },
    });
    fireEvent.change(screen.getByTestId("url-recursive-depth-input"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByTestId("url-recursive-path-prefix-input"), {
      target: { value: "/tutorial/" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("url-recursive-submit"));
    });

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/content/upload/url/recursive");
    expect(init.method).toBe("POST");

    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toEqual({
      url: "https://docs.python.org/3/tutorial/",
      course_id: "course-1",
      max_depth: 3,
      path_prefix: "/tutorial/",
    });

    // Success banner should render with the crawl count.
    const success = await screen.findByTestId("url-recursive-success");
    expect(success.textContent).toContain("Crawled 4 pages");
  });

  it("renders a friendly hint when the backend returns 409", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          detail: "Recursive crawl already in progress for this course",
        },
        409,
      ),
    );

    render(<UrlRecursivePopover courseId="course-1" />);

    fireEvent.change(screen.getByTestId("url-recursive-url-input"), {
      target: { value: "https://docs.python.org/3/tutorial/" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("url-recursive-submit"));
    });

    const conflict = await screen.findByTestId("url-recursive-conflict");
    expect(conflict.textContent).toContain("already running");
    // A generic "error" banner must NOT render alongside the conflict hint —
    // they're mutually exclusive phases.
    expect(screen.queryByTestId("url-recursive-error")).toBeNull();
  });
});
