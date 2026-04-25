import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import DrillCourseTOCPage from "./page";
import type { DrillCourseTOC } from "@/lib/api";
import { ApiError } from "@/lib/api";

const getDrillCourseTOCMock = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getDrillCourseTOC: (...args: unknown[]) => getDrillCourseTOCMock(...args),
  };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "cs50p" }),
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

function makeTOC(): DrillCourseTOC {
  return {
    id: "c1",
    slug: "cs50p",
    title: "CS50P",
    source: "cs50p",
    version: "v1.0.0",
    description: "Compiled Python drills.",
    estimated_hours: 8,
    module_count: 2,
    drill_count: 0,
    passed_count: 0,
    modules: [
      {
        id: "m1",
        slug: "wk00",
        title: "Week 0: Functions",
        order_index: 0,
        outcome: "Practice functions.",
        drill_count: 1,
        drills: [
          {
            id: "d1",
            slug: "hello-world-string",
            title: "Return hello, world",
            why_it_matters: "Canonical greeting.",
            starter_code: "def hello_world(): ...",
            hints: [],
            skill_tags: ["functions"],
            source_citation: "CS50P Week 0",
            time_budget_min: 3,
            difficulty_layer: 1,
            order_index: 1,
          },
        ],
      },
      {
        id: "m2",
        slug: "wk01",
        title: "Week 1: Conditionals",
        order_index: 1,
        outcome: null,
        drill_count: 0,
        drills: [],
      },
    ],
  };
}

describe("/courses/[slug] drill TOC page", () => {
  beforeEach(() => {
    getDrillCourseTOCMock.mockReset();
  });

  it("renders modules and drill rows on success", async () => {
    getDrillCourseTOCMock.mockResolvedValue(makeTOC());
    render(<DrillCourseTOCPage />);

    await waitFor(() => {
      expect(screen.getByTestId("drill-course-modules")).toBeInTheDocument();
    });

    // Course header
    expect(screen.getByText("CS50P")).toBeInTheDocument();
    // Modules rendered
    expect(screen.getByTestId("drill-module-wk00")).toBeInTheDocument();
    expect(screen.getByTestId("drill-module-wk01")).toBeInTheDocument();
    // Drill row with a routable href
    const drillRow = screen.getByTestId("drill-row-hello-world-string");
    expect(drillRow).toHaveAttribute("href", "/practice/d1");
  });

  it("shows the not-seeded copy on 404", async () => {
    getDrillCourseTOCMock.mockRejectedValue(
      new ApiError("course_not_found", { status: 404 }),
    );
    render(<DrillCourseTOCPage />);

    await waitFor(() => {
      expect(screen.getByTestId("drill-course-not-found")).toBeInTheDocument();
    });
    expect(screen.getByText(/Курс не знайдено/)).toBeInTheDocument();
  });

  it("shows an inline error on non-404 failures", async () => {
    getDrillCourseTOCMock.mockRejectedValue(new Error("boom"));
    render(<DrillCourseTOCPage />);

    await waitFor(() => {
      expect(screen.getByTestId("drill-course-error")).toBeInTheDocument();
    });
  });
});
