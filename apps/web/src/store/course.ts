/**
 * Course store using Zustand.
 * Reference: lobe-chat Zustand patterns.
 */

import { create } from "zustand";
import {
  Course,
  ContentNode,
  listCourses,
  createCourse,
  deleteCourse,
  getContentTree,
} from "@/lib/api";

interface CourseState {
  courses: Course[];
  activeCourse: Course | null;
  contentTree: ContentNode[];
  loading: boolean;
  error: string | null;

  fetchCourses: () => Promise<void>;
  setActiveCourse: (course: Course | null) => void;
  addCourse: (name: string, description?: string) => Promise<Course>;
  removeCourse: (id: string) => Promise<void>;
  fetchContentTree: (courseId: string) => Promise<void>;
}

export const useCourseStore = create<CourseState>((set, get) => ({
  courses: [],
  activeCourse: null,
  contentTree: [],
  loading: false,
  error: null,

  fetchCourses: async () => {
    set({ loading: true, error: null });
    try {
      const courses = await listCourses();
      set({ courses, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },

  setActiveCourse: (course) => {
    set({ activeCourse: course, contentTree: [] });
    if (course) {
      get().fetchContentTree(course.id);
    }
  },

  addCourse: async (name, description) => {
    const course = await createCourse(name, description);
    set((s) => ({ courses: [course, ...s.courses] }));
    return course;
  },

  removeCourse: async (id) => {
    await deleteCourse(id);
    set((s) => ({
      courses: s.courses.filter((c) => c.id !== id),
      activeCourse: s.activeCourse?.id === id ? null : s.activeCourse,
    }));
  },

  fetchContentTree: async (courseId) => {
    try {
      const tree = await getContentTree(courseId);
      set({ contentTree: tree });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
}));
