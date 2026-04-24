import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DrillCoursesPage from "./page";
import type { DrillCourseOut } from "@/lib/api";

const listDrillCoursesMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listDrillCourses: (...args: unknown[]) => listDrillCoursesMock(...args),
  };
});

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
    description: "Short, checked Python drills.",
    estimated_hours: 8,
    module_count: 3,
    ...overrides,
  };
}

describe("/courses drill list page", () => {
  beforeEach(() => {
    listDrillCoursesMock.mockReset();
  });

  it("shows the loading skeleton then the course list", async () => {
    listDrillCoursesMock.mockResolvedValue([
      makeCourse(),
      makeCourse({ id: "c2", slug: "py4e", title: "PY4E", module_count: 16 }),
    ]);
    render(<DrillCoursesPage />);

    // Skeleton is visible before the promise resolves
    expect(screen.getByTestId("drill-courses-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("drill-courses-list")).toBeInTheDocument();
    });

    expect(screen.getByTestId("drill-course-card-cs50p")).toHaveAttribute(
      "href",
      "/courses/cs50p",
    );
    expect(screen.getByTestId("drill-course-card-py4e")).toHaveAttribute(
      "href",
      "/courses/py4e",
    );
    expect(screen.getByText("CS50P")).toBeInTheDocument();
    expect(screen.getByText("PY4E")).toBeInTheDocument();
  });

  it("shows an empty-state hint when no courses are seeded", async () => {
    listDrillCoursesMock.mockResolvedValue([]);
    render(<DrillCoursesPage />);

    await waitFor(() => {
      expect(
        screen.queryByTestId("drill-courses-loading"),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText(/Додай курс через/)).toBeInTheDocument();
  });

  it("surfaces an error row with a retry button when the API fails", async () => {
    const user = userEvent.setup();
    listDrillCoursesMock.mockRejectedValueOnce(new Error("boom"));
    render(<DrillCoursesPage />);

    await waitFor(() => {
      expect(screen.getByTestId("drill-courses-error")).toBeInTheDocument();
    });

    // Retry succeeds — list appears
    listDrillCoursesMock.mockResolvedValueOnce([makeCourse()]);
    await user.click(screen.getByText("Спробувати ще раз"));

    await waitFor(() => {
      expect(screen.getByTestId("drill-courses-list")).toBeInTheDocument();
    });
  });
});
