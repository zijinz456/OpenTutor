import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { useWorkspaceStore } from "@/store/workspace";
import { PdfViewerOverlay } from "./pdf-viewer";

const downloadCourseFile = vi.fn();
const trackApiFailure = vi.fn();

vi.mock("@/lib/api", () => ({
  downloadCourseFile: (...args: unknown[]) => downloadCourseFile(...args),
}));

vi.mock("@/lib/error-telemetry", () => ({
  trackApiFailure: (...args: unknown[]) => trackApiFailure(...args),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

describe("PdfViewerOverlay", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({ pdfOverlay: null });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:pdf"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
  });

  it("loads pdf through authenticated binary API path", async () => {
    downloadCourseFile.mockResolvedValue({
      blob: new Blob(["pdf-data"], { type: "application/pdf" }),
      fileName: "lecture.pdf",
      contentType: "application/pdf",
    });
    useWorkspaceStore.getState().openPdf("job-1", "lecture.pdf");

    render(<PdfViewerOverlay courseId="course-1" />);

    await waitFor(() => {
      expect(downloadCourseFile).toHaveBeenCalledWith("job-1");
    });
    expect(screen.getByTitle("lecture.pdf")).toBeInTheDocument();
    expect(trackApiFailure).not.toHaveBeenCalled();
  });

  it("shows visible error and retries on load failure", async () => {
    downloadCourseFile.mockRejectedValue(new Error("Forbidden"));
    useWorkspaceStore.getState().openPdf("job-2", "lecture.pdf");

    const { user } = render(<PdfViewerOverlay courseId="course-1" />);

    await screen.findByText("Forbidden");
    expect(trackApiFailure.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(trackApiFailure).toHaveBeenCalledWith(
      "download",
      expect.any(Error),
      expect.objectContaining({
        endpoint: "/content/files/job-2",
        courseId: "course-1",
      }),
    );

    const callsBeforeRetry = downloadCourseFile.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "pdf.retry" }));
    await waitFor(() => {
      expect(downloadCourseFile.mock.calls.length).toBeGreaterThan(callsBeforeRetry);
    });
  });
});
