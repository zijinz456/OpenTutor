/**
 * Safe localStorage wrapper — handles SSR (window undefined),
 * quota errors, and JSON serialization in one place.
 */

function isAvailable(): boolean {
  return typeof window !== "undefined" && typeof localStorage !== "undefined";
}

export const storage = {
  get<T>(key: string, fallback: T): T {
    if (!isAvailable()) return fallback;
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return fallback;
      return JSON.parse(raw) as T;
    } catch {
      return fallback;
    }
  },

  getRaw(key: string): string | null {
    if (!isAvailable()) return null;
    return localStorage.getItem(key);
  },

  set(key: string, value: unknown): void {
    if (!isAvailable()) return;
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // QuotaExceededError — silently ignore
    }
  },

  setRaw(key: string, value: string): void {
    if (!isAvailable()) return;
    try {
      localStorage.setItem(key, value);
    } catch {
      // QuotaExceededError — silently ignore
    }
  },

  remove(key: string): void {
    if (!isAvailable()) return;
    localStorage.removeItem(key);
  },
};
