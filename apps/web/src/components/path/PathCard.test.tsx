import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PathCard } from "./PathCard";
import type { PathSummary } from "@/lib/api";

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
    description: "Start here for the basics.",
    room_total: 10,
    room_complete: 3,
    task_total: 40,
    task_complete: 15,
    orphan_count: 0,
    ...overrides,
  };
}

describe("<PathCard>", () => {
  it("renders title, difficulty badge, and both progress bars", () => {
    render(<PathCard summary={makePath()} />);
    expect(screen.getByText("Python Fundamentals")).toBeInTheDocument();
    expect(
      screen.getByTestId("path-card-difficulty-python-fundamentals"),
    ).toHaveTextContent(/beginner/i);
    expect(
      screen.getByTestId("path-card-rooms-python-fundamentals"),
    ).toHaveTextContent("3/10");
    expect(
      screen.getByTestId("path-card-tasks-python-fundamentals"),
    ).toHaveTextContent("15/40");
  });

  it("links to /path/{slug}", () => {
    render(<PathCard summary={makePath({ slug: "oop-essentials" })} />);
    const card = screen.getByTestId("path-card-oop-essentials");
    expect(card).toHaveAttribute("href", "/path/oop-essentials");
  });
});
