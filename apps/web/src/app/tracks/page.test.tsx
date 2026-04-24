import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PathListPage from "./page";
import type { PathListResponse, PathSummary } from "@/lib/api";

const listPathsMock = vi.fn();
vi.mock("@/lib/api", async () => ({
  listPaths: (...args: unknown[]) => listPathsMock(...args),
}));

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
    description: "Start here.",
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

describe("/tracks page", () => {
  beforeEach(() => {
    listPathsMock.mockReset();
  });

  it("renders a PathCard for every path once the fetch resolves", async () => {
    listPathsMock.mockResolvedValue(
      makeResponse([
        makePath({ id: "a", slug: "a", title: "Path A" }),
        makePath({ id: "b", slug: "b", title: "Path B" }),
      ]),
    );
    render(<PathListPage />);

    await waitFor(() => {
      expect(screen.getByTestId("path-card-a")).toBeInTheDocument();
    });
    expect(screen.getByTestId("path-card-b")).toBeInTheDocument();
    expect(screen.getByText("Path A")).toBeInTheDocument();
    expect(screen.getByText("Path B")).toBeInTheDocument();
  });
});
