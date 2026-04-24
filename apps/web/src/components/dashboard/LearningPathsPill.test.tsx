import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { LearningPathsPill } from "./LearningPathsPill";
import type { PathListResponse, PathSummary } from "@/lib/api";

const listPathsMock = vi.fn();
vi.mock("@/lib/api", async () => ({
  listPaths: (...args: unknown[]) => listPathsMock(...args),
}));

// Capture the href Link renders so we can assert navigation target
// without standing up a full Next router in jsdom.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.HTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function makePath(overrides: Partial<PathSummary> = {}): PathSummary {
  return {
    id: "p1",
    slug: "python-fundamentals",
    title: "Python Fundamentals",
    difficulty: "beginner",
    track_id: "fundamentals",
    description: null,
    room_total: 10,
    room_complete: 3,
    task_total: 40,
    task_complete: 15,
    orphan_count: 0,
    ...overrides,
  };
}

function makeResponse(
  paths: PathSummary[],
  orphanCount = 0,
): PathListResponse {
  return { paths, orphan_count: orphanCount };
}

describe("<LearningPathsPill>", () => {
  beforeEach(() => {
    listPathsMock.mockReset();
  });

  it("renders aggregate progress across all paths", async () => {
    listPathsMock.mockResolvedValue(
      makeResponse([
        makePath({ id: "a", slug: "a", room_total: 10, room_complete: 3 }),
        makePath({ id: "b", slug: "b", room_total: 12, room_complete: 4 }),
      ]),
    );
    render(<LearningPathsPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("learning-paths-pill-progress"),
      ).toHaveTextContent("7/22 missions cleared");
    });
  });

  it("hides the orphan caption when orphan_count = 0", async () => {
    listPathsMock.mockResolvedValue(makeResponse([makePath()], 0));
    render(<LearningPathsPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("learning-paths-pill-progress"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId("learning-paths-pill-orphans"),
    ).not.toBeInTheDocument();
  });

  it("renders a link to /tracks on the CTA", async () => {
    listPathsMock.mockResolvedValue(makeResponse([makePath()], 5));
    render(<LearningPathsPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("learning-paths-pill-orphans"),
      ).toHaveTextContent("5 cards not yet mapped");
    });
    const cta = screen.getByTestId("learning-paths-pill-cta");
    expect(cta).toHaveAttribute("href", "/tracks");
  });
});
