"use client";

/**
 * Recursive URL crawl popover (§14.5 v2.5 T6).
 *
 * Mirrors `UrlScrapePopover` but adds the knobs the recursive endpoint
 * requires: a depth slider (1-3, default 2) and an optional path-prefix
 * input. Submits to `POST /content/upload/url/recursive` via the
 * `uploadUrlRecursive` client and surfaces loading / success / error
 * states without a toast — the inline banner is easier to test and lines
 * up with `CourseraDropZone`'s UX.
 *
 * ADHD copy: short labels, no guilt, no "are you sure". A 409 ("crawl
 * already in progress") is rendered as a friendly hint rather than a red
 * error because the user's next action is just "wait and retry".
 */

import { useCallback, useState } from "react";
import { Loader2, CheckCircle2, AlertCircle, Info } from "lucide-react";
import {
  uploadUrlRecursive,
  ApiError,
  type RecursiveUrlResponse,
} from "@/lib/api/url_recursive";

interface Props {
  courseId: string;
  onSuccess?: (response: RecursiveUrlResponse) => void;
}

type Phase = "idle" | "submitting" | "success" | "error" | "conflict";

export function UrlRecursivePopover({ courseId, onSuccess }: Props) {
  const [url, setUrl] = useState("");
  const [maxDepth, setMaxDepth] = useState<1 | 2 | 3>(2);
  const [pathPrefix, setPathPrefix] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [response, setResponse] = useState<RecursiveUrlResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");

  const canSubmit =
    phase !== "submitting" &&
    url.trim().length > 0 &&
    (url.startsWith("http://") || url.startsWith("https://"));

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setPhase("submitting");
    setErrorMessage("");
    setResponse(null);
    try {
      const res = await uploadUrlRecursive({
        url: url.trim(),
        course_id: courseId,
        max_depth: maxDepth,
        // Omit when the input is empty so the backend treats it as
        // "same-origin only" rather than "path prefix == empty string".
        ...(pathPrefix.trim() ? { path_prefix: pathPrefix.trim() } : {}),
      });
      setResponse(res);
      setPhase("success");
      onSuccess?.(res);
    } catch (err) {
      // 409 gets its own phase because the UX differs: not a "bad request"
      // the user can retry by fixing the form — they need to wait for the
      // other crawl to finish first.
      if (err instanceof ApiError && err.status === 409) {
        setErrorMessage(
          err.detail || err.message || "A crawl is already running for this course.",
        );
        setPhase("conflict");
        return;
      }
      if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Request failed. Try again.");
      }
      setPhase("error");
    }
  }, [canSubmit, url, courseId, maxDepth, pathPrefix, onSuccess]);

  return (
    <div
      className="flex flex-col gap-3 p-3 rounded-xl border border-border/60 bg-card"
      data-testid="url-recursive-popover"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          Recursive URL crawl
        </h3>
        <span className="text-xs text-muted-foreground">
          BFS, up to 100 pages
        </span>
      </div>

      {/* ---------- URL input ---------- */}
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">Seed URL</span>
        <input
          type="url"
          data-testid="url-recursive-url-input"
          aria-label="Seed URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://docs.python.org/3/tutorial/"
          disabled={phase === "submitting"}
          className="rounded-lg border border-border/60 bg-transparent px-2.5 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
      </label>

      {/* ---------- Depth slider ---------- */}
      <label className="flex flex-col gap-1 text-xs">
        <span className="flex items-center justify-between text-muted-foreground">
          <span>Crawl depth</span>
          <span
            data-testid="url-recursive-depth-value"
            className="font-medium text-foreground"
          >
            {maxDepth}
          </span>
        </span>
        <input
          type="range"
          data-testid="url-recursive-depth-input"
          aria-label="Crawl depth"
          min={1}
          max={3}
          step={1}
          value={maxDepth}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (v === 1 || v === 2 || v === 3) setMaxDepth(v);
          }}
          disabled={phase === "submitting"}
          className="w-full disabled:cursor-not-allowed disabled:opacity-50"
        />
      </label>

      {/* ---------- Path prefix (optional) ---------- */}
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted-foreground">Path prefix (optional)</span>
        <input
          type="text"
          data-testid="url-recursive-path-prefix-input"
          aria-label="Path prefix"
          value={pathPrefix}
          onChange={(e) => setPathPrefix(e.target.value)}
          placeholder="/tutorial/"
          disabled={phase === "submitting"}
          className="rounded-lg border border-border/60 bg-transparent px-2.5 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
      </label>

      {/* ---------- Submit button ---------- */}
      <button
        type="button"
        data-testid="url-recursive-submit"
        onClick={submit}
        disabled={!canSubmit}
        className="h-9 rounded-lg bg-brand px-3 text-sm font-semibold text-brand-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {phase === "submitting" ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 className="size-4 animate-spin" />
            Crawling...
          </span>
        ) : (
          "Start crawl"
        )}
      </button>

      {/* ---------- Success ---------- */}
      {phase === "success" && response && (
        <div
          data-testid="url-recursive-success"
          role="status"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-emerald-300/60 bg-emerald-50/80 text-emerald-950"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold">
              Crawled {response.pages_crawled} page
              {response.pages_crawled === 1 ? "" : "s"}
            </p>
            <p className="text-xs text-emerald-900/80">
              Robots-skipped: {response.pages_skipped_robots} / off-origin:{" "}
              {response.pages_skipped_origin} / failed:{" "}
              {response.pages_fetch_failed}
            </p>
          </div>
        </div>
      )}

      {/* ---------- Concurrent crawl (409) ---------- */}
      {phase === "conflict" && (
        <div
          data-testid="url-recursive-conflict"
          role="status"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-blue-200/60 bg-blue-50/70 text-blue-950"
        >
          <Info className="mt-0.5 size-4 shrink-0 text-blue-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold">A crawl is already running</p>
            <p className="text-xs text-blue-900/80">
              Wait for the previous crawl to finish, then try again.
            </p>
          </div>
        </div>
      )}

      {/* ---------- Error ---------- */}
      {phase === "error" && (
        <div
          data-testid="url-recursive-error"
          role="alert"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-red-300/60 bg-red-50/80 text-red-950"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p
              className="font-semibold"
              data-testid="url-recursive-error-detail"
            >
              {errorMessage}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default UrlRecursivePopover;
