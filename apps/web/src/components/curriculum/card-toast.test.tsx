import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import userEvent from "@testing-library/user-event";
import { CardToast } from "./card-toast";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("CardToast", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a Save prompt when the spawner returned cards", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        cards: [
          { front: "Q1", back: "A1", concept_slug: "intro" },
          { front: "Q2", back: "A2", concept_slug: "intro" },
        ],
      }),
    );

    render(
      <CardToast courseId="c1" sessionId="s1" messageId="m1" />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("card-toast")).toBeInTheDocument();
    });
    expect(screen.getByText(/Save 2 cards\?/)).toBeInTheDocument();
    expect(screen.getByTestId("card-toast-save")).toBeInTheDocument();
    expect(screen.getByTestId("card-toast-dismiss")).toBeInTheDocument();
  });

  it("renders nothing when the backend returned zero cards", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ cards: [], reason: "no_candidates" }),
    );

    render(
      <CardToast courseId="c1" sessionId="s1" messageId="m1" />,
    );

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByTestId("card-toast")).not.toBeInTheDocument();
  });

  it("clicking Save POSTs the candidates and flashes a Saved! marker", async () => {
    // GET /card-candidates
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        cards: [{ front: "Q", back: "A", concept_slug: "intro" }],
      }),
    );
    // POST /save-candidates
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        saved_problem_ids: ["pp1"],
        asset_id: "a1",
        count: 1,
        warnings: [],
      }),
    );

    const user = userEvent.setup();
    render(
      <CardToast courseId="c1" sessionId="s1" messageId="m1" />,
    );
    const saveBtn = await screen.findByTestId("card-toast-save");
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByTestId("card-toast-saved")).toBeInTheDocument();
    });

    // Verify the POST happened with the right URL + body.
    const postCall = mockFetch.mock.calls[1] as [string, RequestInit];
    expect(postCall[0]).toMatch(
      /\/courses\/c1\/flashcards\/save-candidates$/,
    );
    expect(postCall[1].method).toBe("POST");
    const body = JSON.parse(postCall[1].body as string);
    expect(body.candidates).toHaveLength(1);
  });
});
