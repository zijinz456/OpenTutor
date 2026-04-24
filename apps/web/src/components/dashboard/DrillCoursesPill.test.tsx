import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { DrillCoursesPill } from "./DrillCoursesPill";
import type { DrillCourseOut } from "@/lib/api";

const listDrillCoursesMock = vi.fn();
vi.mock("@/lib/api", async () => ({
  listDrillCourses: (...args: unknown[]) => listDrillCoursesMock(...args),
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

function makeCourse(overrides: Partial<DrillCourseOut> = {}): DrillCourseOut {
  return {
    id: "c1",
    slug: "cs50p",
    title: "CS50P",
    source: "cs50p",
    version: "v1.0.0",
    description: null,
    estimated_hours: 8,
    module_count: 3,
    ...overrides,
  };
}

describe("<DrillCoursesPill>", () => {
  beforeEach(() => {
    listDrillCoursesMock.mockReset();
  });

  it("renders aggregate module count across all courses", async () => {
    listDrillCoursesMock.mockResolvedValue([
      makeCourse({ id: "a", slug: "cs50p", module_count: 3 }),
      makeCourse({ id: "b", slug: "py4e", module_count: 16 }),
    ]);
    render(<DrillCoursesPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("drill-courses-pill-progress"),
      ).toHaveTextContent("19 модулів у 2 курсах");
    });
  });

  it("shows empty-state copy when no courses are seeded", async () => {
    listDrillCoursesMock.mockResolvedValue([]);
    render(<DrillCoursesPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("drill-courses-pill-progress"),
      ).toHaveTextContent("Курси ще не засіяні");
    });
  });

  it("renders error text when the API rejects", async () => {
    listDrillCoursesMock.mockRejectedValue(new Error("boom"));
    render(<DrillCoursesPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("drill-courses-pill-error"),
      ).toBeInTheDocument();
    });
  });

  it("routes the CTA to /courses", async () => {
    listDrillCoursesMock.mockResolvedValue([makeCourse()]);
    render(<DrillCoursesPill />);

    await waitFor(() => {
      expect(
        screen.getByTestId("drill-courses-pill-progress"),
      ).toBeInTheDocument();
    });
    const cta = screen.getByTestId("drill-courses-pill-cta");
    expect(cta).toHaveAttribute("href", "/courses");
  });
});
