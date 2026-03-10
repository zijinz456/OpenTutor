export type TranslateFn = (key: string) => string;
export type TranslateFormatFn = (key: string, vars?: Record<string, string | number | null | undefined>) => string;

export function formatDateLabel(raw: string | null, fallback: string): string {
  if (!raw) return fallback;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return fallback;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function getDaysLeft(raw: string | null): number | null {
  if (!raw) return null;
  const target = new Date(raw).getTime();
  if (Number.isNaN(target)) return null;
  return Math.ceil((target - Date.now()) / 86_400_000);
}
