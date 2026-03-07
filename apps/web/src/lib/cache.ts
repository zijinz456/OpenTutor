/**
 * Lightweight in-memory TTL cache for API responses.
 *
 * Designed to be used inside Zustand stores so that repeated page loads /
 * re-renders don't trigger redundant network requests.  Each cache entry is
 * keyed by an arbitrary string and expires after a configurable TTL.
 *
 * Usage:
 *   import { ttlCache } from "@/lib/cache";
 *
 *   // In a Zustand store action:
 *   const cached = ttlCache.get<Course[]>("courses");
 *   if (cached) { set({ courses: cached }); return; }
 *   const courses = await listCourseOverview();
 *   ttlCache.set("courses", courses, 60_000);
 *   set({ courses });
 */

interface CacheEntry<T = unknown> {
  data: T;
  /** Unix-ms timestamp when this entry was written. */
  storedAt: number;
  /** Time-to-live in milliseconds. */
  ttlMs: number;
}

class TtlCache {
  private store = new Map<string, CacheEntry>();

  /**
   * Retrieve a cached value if it exists and has not expired.
   * Returns `undefined` when the key is missing or stale.
   */
  get<T>(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;
    if (Date.now() - entry.storedAt > entry.ttlMs) {
      this.store.delete(key);
      return undefined;
    }
    return entry.data as T;
  }

  /**
   * Store a value under `key` with a given TTL (in milliseconds).
   */
  set<T>(key: string, data: T, ttlMs: number): void {
    this.store.set(key, { data, storedAt: Date.now(), ttlMs });
  }

  /**
   * Returns true if `key` is present and has NOT yet expired.
   */
  has(key: string): boolean {
    return this.get(key) !== undefined;
  }

  /**
   * Remove a single key from the cache (e.g. after a mutation that
   * invalidates the data).
   */
  invalidate(key: string): void {
    this.store.delete(key);
  }

  /**
   * Remove every entry from the cache.
   */
  invalidateAll(): void {
    this.store.clear();
  }
}

/** Singleton cache instance shared across all stores. */
export const ttlCache = new TtlCache();