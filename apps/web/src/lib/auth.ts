const TOKEN_STORAGE_KEYS = [
  "access_token",
  "accessToken",
  "auth.access_token",
  "authToken",
  "token",
  "opentutor.access_token",
  "opentutor.auth",
  "opentutor.session",
] as const;

const TOKEN_COOKIE_KEYS = [
  "access_token",
  "auth_token",
  "token",
] as const;

function extractTokenFromObject(value: Record<string, unknown>): string | null {
  const directKeys = ["access_token", "accessToken", "token"] as const;
  for (const key of directKeys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }

  const nested = value.tokens;
  if (nested && typeof nested === "object") {
    return extractTokenFromObject(nested as Record<string, unknown>);
  }

  return null;
}

function normalizeToken(raw: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;

  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (typeof parsed === "string") {
      return parsed.trim() || null;
    }
    if (parsed && typeof parsed === "object") {
      return extractTokenFromObject(parsed as Record<string, unknown>);
    }
  } catch {
    // Fall back to treating the value as a raw token string.
  }

  return trimmed;
}

function readFromStorage(storage: Storage): string | null {
  for (const key of TOKEN_STORAGE_KEYS) {
    const token = normalizeToken(storage.getItem(key));
    if (token) return token;
  }
  return null;
}

function readFromCookies(): string | null {
  if (typeof document === "undefined" || !document.cookie) {
    return null;
  }

  const cookies = document.cookie.split(";").map((entry) => entry.trim());
  for (const key of TOKEN_COOKIE_KEYS) {
    const prefix = `${key}=`;
    const match = cookies.find((cookie) => cookie.startsWith(prefix));
    if (!match) continue;
    const token = normalizeToken(decodeURIComponent(match.slice(prefix.length)));
    if (token) return token;
  }
  return null;
}

export function getStoredAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const localToken = readFromStorage(window.localStorage);
  if (localToken) return localToken;

  const sessionToken = readFromStorage(window.sessionStorage);
  if (sessionToken) return sessionToken;

  return readFromCookies();
}

export function buildAuthHeaders(headers?: HeadersInit): Headers {
  const resolved = new Headers(headers);
  const token = getStoredAccessToken();
  if (token && !resolved.has("Authorization")) {
    resolved.set("Authorization", `Bearer ${token}`);
  }
  return resolved;
}
