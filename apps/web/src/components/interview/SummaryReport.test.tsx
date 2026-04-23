/**
 * Unit tests for <SummaryReport> (Phase 5 T6e).
 *
 * We mock `globalThis.fetch` and let the real component-to-api path run,
 * mirroring CourseraDropZone.test.tsx. The save-gaps endpoint returns
 * `{saved_problem_ids, count, ...}`-shaped data; the interview API
 * client already returns `{saved_count, problem_ids}` so we post that
 * shape back from the mock.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { SummaryReport } from "./SummaryReport";
import type { SummaryResponse } from "@/lib/api/interview";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const baseSummary: SummaryResponse = {
  avg_by_dimension: {
    Correctness: 3.7,
    Depth: 2.3,
    Tradeoff: 2.0,
    Clarity: 4.3,
  },
  weakest_dimensions: ["Depth", "Tradeoff"],
  worst_turn_id: "turn-7",
  answer_time_ms_avg: 45_000,
  total_answer_time_s: 540,
};

describe("SummaryReport", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  afterEach(() => {
    document.cookie = "csrf_token=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/";
  });

  it("renders averages, highlights weakest dims, shows save CTA", () => {
    render(
      <SummaryReport
        summary={baseSummary}
        sessionId="sess-1"
        turnIds={["t1", "t2", "t3"]}
      />,
    );

    expect(screen.getByTestId("summary-report")).toBeInTheDocument();
    // Four dim rows; Depth + Tradeoff flagged weak.
    expect(
      screen.getByTestId("summary-avg-Correctness").getAttribute("data-is-weak"),
    ).toBe("0");
    expect(
      screen.getByTestId("summary-avg-Depth").getAttribute("data-is-weak"),
    ).toBe("1");
    expect(
      screen.getByTestId("summary-avg-Tradeoff").getAttribute("data-is-weak"),
    ).toBe("1");
    expect(screen.getByTestId("summary-weak-tag-Depth")).toBeInTheDocument();
    expect(screen.getByTestId("summary-weak-tag-Tradeoff")).toBeInTheDocument();

    // Averages rendered to 1 decimal.
    expect(screen.getByTestId("summary-avg-Correctness").textContent).toContain(
      "3.7",
    );
    expect(screen.getByTestId("summary-avg-Depth").textContent).toContain("2.3");

    // Timing line + CTA button with count.
    expect(screen.getByTestId("summary-time").textContent).toContain("540s");
    const cta = screen.getByTestId("summary-save-gaps");
    expect(cta.textContent).toContain("Save 3 gap flashcards");
    expect(cta).not.toBeDisabled();
  });

  it("clicks save → POSTs turn_ids, fires onSaved, swaps to saved state", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ saved_count: 3, problem_ids: ["p1", "p2", "p3"] }),
    );
    const onSaved = vi.fn();
    render(
      <SummaryReport
        summary={baseSummary}
        sessionId="sess-42"
        turnIds={["turn-a", "turn-b", "turn-c"]}
        onSaved={onSaved}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId("summary-save-gaps"));
    });

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/interview/sess-42/save-gaps");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.turn_ids).toEqual(["turn-a", "turn-b", "turn-c"]);

    await screen.findByTestId("summary-saved");
    expect(onSaved).toHaveBeenCalledWith({ saved_count: 3 });
    // CTA button is gone once saved.
    expect(screen.queryByTestId("summary-save-gaps")).not.toBeInTheDocument();
  });
});
