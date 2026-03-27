import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSetup } from "./use-setup";

const push = vi.fn();
const addCourse = vi.fn();
const submitSources = vi.fn();
const applyDefaultPreferences = vi.fn();
const persistWorkspaceLayout = vi.fn();
const buildCourseMetadata = vi.fn();
const getHealthStatus = vi.fn();
const getLlmRuntimeConfig = vi.fn();
const updateLlmRuntimeConfig = vi.fn();
const testLlmRuntimeConnection = vi.fn();
const getDemoCourse = vi.fn();
const listIngestionJobs = vi.fn();
const listAuthSessions = vi.fn();
const canvasBrowserLogin = vi.fn();
const streamChat = vi.fn();
const t = (key: string) => key;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => ({
    get: (key: string) => (key === "step" ? "content" : null),
  }),
}));

vi.mock("@/store/course", () => ({
  useCourseStore: () => ({ addCourse }),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => t,
}));

vi.mock("../new/parse-actions", () => ({
  submitSources: (...args: unknown[]) => submitSources(...args),
}));

vi.mock("./setup-helpers", () => ({
  validateNameValue: vi.fn(() => null),
  validateUrlValue: vi.fn(() => ({ error: null, isCanvas: false })),
  applyDefaultPreferences: (...args: unknown[]) => applyDefaultPreferences(...args),
  buildCourseMetadata: (...args: unknown[]) => buildCourseMetadata(...args),
  persistWorkspaceLayout: (...args: unknown[]) => persistWorkspaceLayout(...args),
}));

vi.mock("@/lib/api", () => ({
  getHealthStatus: (...args: unknown[]) => getHealthStatus(...args),
  getLlmRuntimeConfig: (...args: unknown[]) => getLlmRuntimeConfig(...args),
  updateLlmRuntimeConfig: (...args: unknown[]) => updateLlmRuntimeConfig(...args),
  testLlmRuntimeConnection: (...args: unknown[]) => testLlmRuntimeConnection(...args),
  getDemoCourse: (...args: unknown[]) => getDemoCourse(...args),
  listIngestionJobs: (...args: unknown[]) => listIngestionJobs(...args),
  listAuthSessions: (...args: unknown[]) => listAuthSessions(...args),
  canvasBrowserLogin: (...args: unknown[]) => canvasBrowserLogin(...args),
  streamChat: (...args: unknown[]) => streamChat(...args),
}));

describe("useSetup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getHealthStatus.mockResolvedValue({ llm_status: "ready" });
    getLlmRuntimeConfig.mockResolvedValue({ provider: "ollama", model: "llama3.2:3b", llm_required: false });
    listIngestionJobs.mockResolvedValue([]);
    listAuthSessions.mockResolvedValue([]);
    streamChat.mockResolvedValue((async function* () {})());
    addCourse.mockResolvedValue({ id: "course-123" });
    applyDefaultPreferences.mockResolvedValue([]);
    persistWorkspaceLayout.mockImplementation(() => {});
    buildCourseMetadata.mockReturnValue({ metadata: { workspace_features: {} }, sourceMode: "upload" });
    submitSources.mockResolvedValue(true);
  });

  it("moves from content to interview on startLearning", async () => {
    const { result } = renderHook(() => useSetup());
    await waitFor(() => {
      expect(result.current.llmChecking).toBe(false);
      expect(result.current.step).toBe("content");
    });

    act(() => {
      void result.current.startLearning();
    });

    expect(result.current.step).toBe("interview");
  });

  it("quickStart enters discovery with a default workspace", async () => {
    const { result } = renderHook(() => useSetup());
    await waitFor(() => {
      expect(result.current.llmChecking).toBe(false);
      expect(result.current.step).toBe("content");
    });

    act(() => {
      result.current.setProjectName("Quick Start Physics");
      result.current.setFiles([
        {
          file: new File(["# waves"], "waves.md", { type: "text/markdown" }),
          name: "waves.md",
          size: "8 KB",
        },
      ]);
    });

    await act(async () => {
      await result.current.quickStart();
    });

    expect(result.current.step).toBe("discovery");
    expect(result.current.createdCourseId).toBe("course-123");
    expect(submitSources).toHaveBeenCalledTimes(1);
    expect(persistWorkspaceLayout).toHaveBeenCalledWith(
      "course-123",
      "stem_student",
      "course_following",
      null,
    );
  });

  it("transitions confirmTemplate to discovery without immediate navigation", async () => {
    const { result } = renderHook(() => useSetup());
    await waitFor(() => {
      expect(result.current.llmChecking).toBe(false);
    });

    act(() => {
      result.current.setStep("template");
      result.current.setSelectedTemplate("stem_student");
      result.current.setSelectedMode("course_following");
      result.current.setProjectName("Physics 101");
    });

    await act(async () => {
      await result.current.confirmTemplate();
    });

    await waitFor(() => {
      expect(submitSources).toHaveBeenCalledTimes(1);
    });
    expect(result.current.step).toBe("discovery");
    expect(result.current.createdCourseId).toBe("course-123");
    expect(push).not.toHaveBeenCalled();
  });

  it("navigates to workspace in enterWorkspace", async () => {
    const { result } = renderHook(() => useSetup());
    await waitFor(() => {
      expect(result.current.llmChecking).toBe(false);
    });

    act(() => {
      result.current.setStep("template");
      result.current.setSelectedTemplate("stem_student");
      result.current.setSelectedMode("course_following");
    });

    await act(async () => {
      await result.current.confirmTemplate();
    });

    await act(async () => {
      await result.current.enterWorkspace();
    });

    expect(push).toHaveBeenCalledWith("/course/course-123");
  });
});
