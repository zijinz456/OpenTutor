import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { DataExportSection } from "./DataExportSection";

const downloadExportSession = vi.fn();
const trackApiFailure = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  downloadExportSession: (...args: unknown[]) => downloadExportSession(...args),
}));

vi.mock("@/lib/error-telemetry", () => ({
  trackApiFailure: (...args: unknown[]) => trackApiFailure(...args),
}));

vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
  },
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

describe("DataExportSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:mock"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
  });

  it("downloads export through binary client path", async () => {
    downloadExportSession.mockResolvedValue({
      blob: new Blob(["csv-data"], { type: "text/csv" }),
      fileName: "session-export.csv",
      contentType: "text/csv",
    });

    const { user } = render(<DataExportSection />);
    await user.click(screen.getByRole("button", { name: "settings.exportButton" }));

    await waitFor(() => {
      expect(downloadExportSession).toHaveBeenCalledTimes(1);
    });
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
    expect(trackApiFailure).not.toHaveBeenCalled();
  });

  it("shows visible error and telemetry when export fails", async () => {
    downloadExportSession.mockRejectedValue(new Error("Unauthorized"));

    const { user } = render(<DataExportSection />);
    await user.click(screen.getByRole("button", { name: "settings.exportButton" }));

    await screen.findByText("Unauthorized");
    expect(trackApiFailure).toHaveBeenCalledTimes(1);
    expect(trackApiFailure).toHaveBeenCalledWith(
      "download",
      expect.any(Error),
      expect.objectContaining({ endpoint: "/export/session" }),
    );
    expect(toastError).toHaveBeenCalledTimes(1);
  });
});
