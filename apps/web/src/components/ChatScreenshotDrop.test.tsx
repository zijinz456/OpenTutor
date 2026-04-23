/**
 * Unit tests for <ChatScreenshotDrop> (Phase 4 T5c).
 *
 * We mock the course store + the inner <ScreenshotDropZone> so this file
 * stays scoped to the wrapper's mount/dismiss behaviour. The dropzone
 * itself is covered end-to-end by ScreenshotDropZone.test.tsx; here we
 * only need a marker element with the same testid so the wrapper's
 * "renders both" / "hides on no course" / "dismiss keeps dropzone"
 * invariants are observable.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Hoisted mock state — the vi.mock factory below reads this at module
// resolution time, so mutating it per-test is enough to steer the
// component's rendered output.
const courseStoreState: { activeCourse: { id: string; name: string } | null } = {
  activeCourse: { id: "course-1", name: "Test course" },
};

vi.mock("@/store/course", () => ({
  useCourseStore: (selector: (s: typeof courseStoreState) => unknown) =>
    selector(courseStoreState),
}));

// Neutralise sonner so the success-toast handler in the wrapper is a no-op.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Stub the real dropzone — we don't want its fetch / paste listeners
// running in these tests. A single testid div is enough to assert the
// wrapper mounted it.
vi.mock("./ScreenshotDropZone", () => ({
  ScreenshotDropZone: ({ courseId }: { courseId: string }) => (
    <div data-testid="screenshot-drop-zone" data-course-id={courseId} />
  ),
}));

import { ChatScreenshotDrop } from "./ChatScreenshotDrop";

describe("ChatScreenshotDrop", () => {
  it("renders both privacy banner and dropzone when course is active", () => {
    courseStoreState.activeCourse = { id: "course-1", name: "Test course" };
    render(<ChatScreenshotDrop />);

    expect(screen.getByTestId("chat-screenshot-drop")).toBeInTheDocument();
    expect(
      screen.getByTestId("screenshot-privacy-banner"),
    ).toBeInTheDocument();
    const dropzone = screen.getByTestId("screenshot-drop-zone");
    expect(dropzone).toBeInTheDocument();
    // Wrapper must forward the active course id down to the dropzone.
    expect(dropzone.getAttribute("data-course-id")).toBe("course-1");
  });

  it("hides when no active course", () => {
    courseStoreState.activeCourse = null;
    const { container } = render(<ChatScreenshotDrop />);

    expect(container.firstChild).toBeNull();
    expect(
      screen.queryByTestId("chat-screenshot-drop"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("screenshot-privacy-banner"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("screenshot-drop-zone"),
    ).not.toBeInTheDocument();
  });

  it("dismissing privacy banner keeps dropzone mounted", () => {
    courseStoreState.activeCourse = { id: "course-1", name: "Test course" };
    render(<ChatScreenshotDrop />);

    expect(
      screen.getByTestId("screenshot-privacy-banner"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByTestId("screenshot-privacy-banner-dismiss"),
    );

    // Banner is gone, but the dropzone (and the wrapper shell) remain.
    expect(
      screen.queryByTestId("screenshot-privacy-banner"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("chat-screenshot-drop")).toBeInTheDocument();
    expect(screen.getByTestId("screenshot-drop-zone")).toBeInTheDocument();
  });
});
