/**
 * Course store using Zustand.
 * Reference: lobe-chat Zustand patterns.
 */

import { create } from "zustand";
import {
  Course,
  CourseMetadata,
  ContentNode,
  IngestionJobSummary,
  listCourseOverview,
  createCourse,
  getContentTree,
  listIngestionJobs,
} from "@/lib/api";
import { ttlCache } from "@/lib/cache";

/** Cache key & TTL for the course overview list (dashboard). */
const COURSES_CACHE_KEY = "courses:overview";
const COURSES_TTL_MS = 60_000; // 60 seconds

interface CourseState {
  courses: Course[];
  activeCourse: Course | null;
  contentTree: ContentNode[];
  ingestionJobs: IngestionJobSummary[];
  loading: boolean;
  error: string | null;

  fetchCourses: () => Promise<void>;
  setActiveCourse: (course: Course | null) => void;
  addCourse: (name: string, description?: string, metadata?: CourseMetadata) => Promise<Course>;
  fetchContentTree: (courseId: string) => Promise<void>;
  fetchIngestionJobs: (courseId: string) => Promise<void>;
}

export const useCourseStore = create<CourseState>((set, get) => ({
  courses: [],
  activeCourse: null,
  contentTree: [],
  ingestionJobs: [],
  loading: false,
  error: null,

  fetchCourses: async () => {
    // Return cached data immediately if still fresh.
    const cached = ttlCache.get<Course[]>(COURSES_CACHE_KEY);
    if (cached) {
      set({ courses: cached, loading: false, error: null });
      return;
    }

    set({ loading: true, error: null });
    try {
      const courses = await listCourseOverview();
      ttlCache.set(COURSES_CACHE_KEY, courses, COURSES_TTL_MS);
      set({ courses, loading: false, error: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load courses";
      set({ loading: false, error: message });
    }
  },

  setActiveCourse: (course) => {
    set({ activeCourse: course, contentTree: [], error: null });
    if (course) {
      get().fetchContentTree(course.id);
    }
  },

  addCourse: async (name, description, metadata) => {
    const course = await createCourse(name, description, metadata);
    ttlCache.invalidate(COURSES_CACHE_KEY);
    set((s) => ({ courses: [course, ...s.courses], error: null }));
    return course;
  },

  fetchContentTree: async (courseId) => {
    try {
      const tree = await getContentTree(courseId);
      set({ contentTree: tree, error: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load course content";
      set({ error: message });
    }
  },

  fetchIngestionJobs: async (courseId) => {
    try {
      const jobs = await listIngestionJobs(courseId);
      set({ ingestionJobs: jobs, error: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load ingestion jobs";
      set({ error: message });
    }
  },
}));
