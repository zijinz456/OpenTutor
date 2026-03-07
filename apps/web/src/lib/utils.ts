import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const safeLocalStorage = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return fallback;
      return JSON.parse(raw) as T;
    } catch {
      console.warn(`[safeLocalStorage] corrupt data for key "${key}", returning fallback`);
      try { localStorage.removeItem(key); } catch { /* ignore */ }
      return fallback;
    }
  },

  set(key: string, value: unknown): void {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      console.warn(`[safeLocalStorage] failed to write key "${key}":`, e);
    }
  },

  remove(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch { /* ignore */ }
  },
};
