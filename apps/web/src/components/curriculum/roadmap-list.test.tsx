import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { RoadmapList } from "./roadmap-list";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("RoadmapList", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("renders one list item per roadmap entry with mastery percent", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse([
        {
          node_id: "n1",
          slug: "alpha",
          topic: "Alpha",
          blurb: "first topic",
          mastery_score: 0.0,
          position: 0,
        },
        {
          node_id: "n2",
          slug: "beta",
          topic: "Beta",
          blurb: null,
          mastery_score: 0.5,
          position: 1,
        },
        {
          node_id: "n3",
          slug: "gamma",
          topic: "Gamma",
          blurb: "third",
          mastery_score: 1.0,
          position: 2,
        },
      ]),
    );

    render(<RoadmapList courseId="course-1" />);

    await waitFor(() => {
      expect(screen.getByTestId("roadmap-list")).toBeInTheDocument();
    });
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Gamma")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("renders nothing when the roadmap is empty", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse([]));
    const { container } = render(<RoadmapList courseId="course-1" />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    // The component renders no list; after the loading flip it should
    // still have no visible list element.
    expect(screen.queryByTestId("roadmap-list")).not.toBeInTheDocument();
    expect(container.querySelector("ul")).toBeNull();
  });
});
