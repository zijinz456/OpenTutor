/**
 * Convenience re-export of test utilities.
 *
 * Usage in tests:
 *   import { render, screen } from "@/test-utils";
 */

export { render, screen, waitFor, within, act } from "@/test-utils/render";

// Re-export locale strings so tests can assert against real copy
import en from "@/locales/en.json";
export const messages = en as Record<string, string>;

/**
 * Look up a translation key from the English locale bundle.
 * Returns the key itself when no translation is found (mirrors the app fallback).
 */
export function t(key: string): string {
  return (en as Record<string, string>)[key] ?? key;
}
