import { describe, it, expect, vi, beforeEach } from "vitest";
import { useCourseStore } from "./course";

// Mock API functions
vi.mock("@/lib/api", () => ({
  listCourseOverview: vi.fn(),
  createCourse: vi.fn(),
  getContentTree: vi.fn(),
  listIngestionJobs: vi.fn(),
}));

vi.mock("@/lib/cache", () => ({
  ttlCache: {
    get: vi.fn(() => null),
    set: vi.fn(),
    invalidate: vi.fn(),
  },
}));

import {
  listCourseOverview,
  createCourse,
  getContentTree,
  listIngestionJobs,
} from "@/lib/api";
import { ttlCache } from "@/lib/cache";

const mockListCourseOverview = vi.mocked(listCourseOverview);
const mockCreateCourse = vi.mocked(createCourse);
const mockGetContentTree = vi.mocked(getContentTree);
const mockListIngestionJobs = vi.mocked(listIngestionJobs);
const mockTtlCache = vi.mocked(ttlCache);

const fakeCourse = {
  id: "c1",
  name: "Math 101",
  description: "Intro math",
  created_at: "2026-01-01",
  metadata: {},
};

describe("useCourseStore", () => {
  beforeEach(() => {
    // Reset store between tests
    useCourseStore.setState({
      courses: [],
      activeCourse: null,
      contentTree: [],
      ingestionJobs: [],
      loading: false,
      error: null,
    });
    vi.clearAllMocks();
    mockTtlCache.get.mockReturnValue(null);
  });

  describe("fetchCourses", () => {
    it("fetches and sets courses", async () => {
      mockListCourseOverview.mockResolvedValueOnce([fakeCourse] as never);

      await useCourseStore.getState().fetchCourses();

      const state = useCourseStore.getState();
      expect(state.courses).toEqual([fakeCourse]);
      expect(state.loading).toBe(false);
      expect(state.error).toBeNull();
    });

    it("uses cached data when available", async () => {
      mockTtlCache.get.mockReturnValueOnce([fakeCourse]);

      await useCourseStore.getState().fetchCourses();

      expect(mockListCourseOverview).not.toHaveBeenCalled();
      expect(useCourseStore.getState().courses).toEqual([fakeCourse]);
    });

    it("sets error on failure", async () => {
      mockListCourseOverview.mockRejectedValueOnce(
        new Error("Network error") as never
      );

      await useCourseStore.getState().fetchCourses();

      const state = useCourseStore.getState();
      expect(state.error).toBe("Network error");
      expect(state.loading).toBe(false);
    });
  });

  describe("addCourse", () => {
    it("creates course and prepends to list", async () => {
      mockCreateCourse.mockResolvedValueOnce(fakeCourse as never);

      const result = await useCourseStore.getState().addCourse("Math 101", "Intro math");

      expect(result).toEqual(fakeCourse);
      expect(useCourseStore.getState().courses[0]).toEqual(fakeCourse);
      expect(mockTtlCache.invalidate).toHaveBeenCalled();
    });
  });

  describe("setActiveCourse", () => {
    it("sets active course and triggers content tree fetch", () => {
      mockGetContentTree.mockResolvedValueOnce([] as never);

      useCourseStore.getState().setActiveCourse(fakeCourse as never);

      const state = useCourseStore.getState();
      expect(state.activeCourse).toEqual(fakeCourse);
      expect(mockGetContentTree).toHaveBeenCalledWith("c1");
    });

    it("clears content tree when setting null", () => {
      useCourseStore.setState({ contentTree: [{ id: "node1" }] as never });

      useCourseStore.getState().setActiveCourse(null);

      expect(useCourseStore.getState().contentTree).toEqual([]);
      expect(mockGetContentTree).not.toHaveBeenCalled();
    });
  });

  describe("fetchContentTree", () => {
    it("fetches and sets content tree", async () => {
      const tree = [{ id: "ch1", title: "Chapter 1", children: [] }];
      mockGetContentTree.mockResolvedValueOnce(tree as never);

      await useCourseStore.getState().fetchContentTree("c1");

      expect(useCourseStore.getState().contentTree).toEqual(tree);
    });

    it("sets error on failure", async () => {
      mockGetContentTree.mockRejectedValueOnce(new Error("Failed") as never);

      await useCourseStore.getState().fetchContentTree("c1");

      expect(useCourseStore.getState().error).toBe("Failed");
    });
  });

  describe("fetchIngestionJobs", () => {
    it("fetches and sets ingestion jobs", async () => {
      const jobs = [{ id: "j1", status: "completed" }];
      mockListIngestionJobs.mockResolvedValueOnce(jobs as never);

      await useCourseStore.getState().fetchIngestionJobs("c1");

      expect(useCourseStore.getState().ingestionJobs).toEqual(jobs);
    });
  });
});
