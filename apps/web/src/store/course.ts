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

  fetchCourses: async () => {
    // Return cached data immediately if still fresh.
    const cached = ttlCache.get<Course[]>(COURSES_CACHE_KEY);
    if (cached) {
      set({ courses: cached, loading: false });
      return;
    }

    set({ loading: true });
    try {
      const courses = await listCourseOverview();
      ttlCache.set(COURSES_CACHE_KEY, courses, COURSES_TTL_MS);
      set({ courses, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  setActiveCourse: (course) => {
    set({ activeCourse: course, contentTree: [] });
    if (course) {
      get().fetchContentTree(course.id);
    }
  },

  addCourse: async (name, description, metadata) => {
    const course = await createCourse(name, description, metadata);
    ttlCache.invalidate(COURSES_CACHE_KEY);
    set((s) => ({ courses: [course, ...s.courses] }));
    return course;
  },

  fetchContentTree: async (courseId) => {
    try {
      const tree = await getContentTree(courseId);
      set({ contentTree: tree });
    } catch {
      // silently fail
    }
  },

  fetchIngestionJobs: async (courseId) => {
    try {
      const jobs = await listIngestionJobs(courseId);
      set({ ingestionJobs: jobs });
    } catch {
      // silently fail
    }
  },
}));
