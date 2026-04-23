"use client";

/**
 * Screenshot-to-drill drop zone (Phase 4 T4).
 *
 * Drop (or Ctrl+V paste) a PNG/JPEG/WebP → optional canvas downsample to
 * 1600px long-side → POST to `/content/upload/screenshot` → preview 3-5
 * vision-extracted flashcards → click `Save all` → POST to existing
 * `save-candidates` endpoint with `spawn_origin="screenshot"` → cards land
 * in the FSRS queue.
 *
 * ADHD copy: short, imperative, no confirm modals, no guilt. Errors
 * surface the backend's `detail + hint` so the user knows what to fix
 * instead of reshooting blindly.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  ImagePlus,
  Loader2,
  Sparkles,
  X,
} from "lucide-react";
import {
  ApiError,
  saveScreenshotCandidates,
  uploadScreenshot,
} from "@/lib/api/screenshot";
import type {
  CardCandidate,
  ScreenshotCandidatesResponse,
  ScreenshotSaveResult,
} from "@/lib/api/screenshot";

interface Props {
  courseId: string;
  onSaved?: (result: ScreenshotSaveResult) => void;
}

type Phase =
  | "idle"
  | "uploading"
  | "preview"
  | "saving"
  | "saved"
  | "error";

interface ErrorState {
  detail: string;
  hint?: string;
}

/** Longest edge (px) we allow before canvas downsample — matches T4 spec. */
const MAX_LONG_SIDE = 1600;

/** Accept filter used both on <input type="file"> and on drop/paste MIME. */
const ACCEPT_MIME = "image/png,image/jpeg,image/webp";
const ACCEPTED_MIME_SET = new Set(["image/png", "image/jpeg", "image/webp"]);

/**
 * Map ApiError → ADHD-copy `{detail, hint}`. Keeps the component branchless
 * by centralising the error-code-to-copy table in one place.
 */
function apiErrorToState(err: ApiError): ErrorState {
  switch (err.status) {
    case 413:
      return {
        detail: "Screenshot too large (max 5 MiB).",
        hint: "Downsample and retry.",
      };
    case 415:
      return {
        detail: "Unsupported format.",
        hint: "Use PNG, JPEG, or WebP.",
      };
    case 429:
      return {
        detail: "Too fast — wait 60s.",
        hint: "Max 5 screenshots per minute.",
      };
    case 404:
      return {
        detail: "Course not found.",
      };
    default:
      return {
        detail: err.detail ?? err.message ?? "Upload failed.",
      };
  }
}

/**
 * If the image's long side exceeds MAX_LONG_SIDE, re-encode it through a
 * canvas at the scaled-down size. Returns the original File untouched when
 * no downsample is needed, so we never pay the encode cost for small
 * screenshots.
 *
 * Encoded as PNG for PNG input, otherwise JPEG at q=0.9 — matching what
 * gpt-4o-mini's 768-px vision tile would down-convert to anyway.
 */
async function maybeDownsample(file: File): Promise<File | Blob> {
  if (!ACCEPTED_MIME_SET.has(file.type)) return file;

  const img = new Image();
  const objectUrl = URL.createObjectURL(file);
  try {
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("image decode failed"));
      img.src = objectUrl;
    });

    const { naturalWidth: w, naturalHeight: h } = img;
    if (w <= MAX_LONG_SIDE && h <= MAX_LONG_SIDE) return file;

    const scale = MAX_LONG_SIDE / Math.max(w, h);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const outMime = file.type === "image/png" ? "image/png" : "image/jpeg";
    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob(resolve, outMime, 0.9),
    );
    if (!blob) return file;
    return new File([blob], file.name, { type: outMime });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

/** Truncate for preview — vision often returns right at the max-length limit. */
function truncate(s: string, n: number): string {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}

export function ScreenshotDropZone({ courseId, onSaved }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [dragging, setDragging] = useState(false);
  const [candidates, setCandidates] = useState<CardCandidate[]>([]);
  const [screenshotHash, setScreenshotHash] = useState<string>("");
  const [saveResult, setSaveResult] = useState<ScreenshotSaveResult | null>(
    null,
  );
  const [error, setError] = useState<ErrorState | null>(null);

  const reset = useCallback(() => {
    setPhase("idle");
    setDragging(false);
    setCandidates([]);
    setScreenshotHash("");
    setSaveResult(null);
    setError(null);
  }, []);

  /**
   * Core upload path shared by drop, file-picker, and clipboard paste.
   * Runs downsample → POST → transitions to `preview` or `error`.
   */
  const processFile = useCallback(
    async (file: File) => {
      if (!ACCEPTED_MIME_SET.has(file.type)) {
        // Silently ignore — drag-drop and paste both can pick up stray
        // non-image payloads (e.g. rich-text). No red error for that.
        return;
      }
      setPhase("uploading");
      setError(null);
      try {
        const toUpload = await maybeDownsample(file);
        const res: ScreenshotCandidatesResponse = await uploadScreenshot(
          courseId,
          toUpload,
        );
        setCandidates(res.candidates);
        setScreenshotHash(res.screenshot_hash);
        setPhase("preview");
      } catch (err) {
        if (err instanceof ApiError) {
          setError(apiErrorToState(err));
        } else if (err instanceof Error) {
          setError({ detail: err.message });
        } else {
          setError({ detail: "Upload failed. Try again." });
        }
        setPhase("error");
      }
    },
    [courseId],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const picked = e.target.files?.[0];
      if (picked) void processFile(picked);
      e.target.value = "";
    },
    [processFile],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      const dropped = e.dataTransfer.files?.[0];
      if (dropped) void processFile(dropped);
    },
    [processFile],
  );

  /**
   * Global `paste` listener — mounted while the component exists. We
   * filter to image MIMEs only, so paste of text / richtext is ignored
   * and doesn't steal paste focus from inputs elsewhere on the page.
   */
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.kind === "file" && ACCEPTED_MIME_SET.has(item.type)) {
          const file = item.getAsFile();
          if (file) {
            e.preventDefault();
            void processFile(file);
            return;
          }
        }
      }
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [processFile]);

  const save = useCallback(async () => {
    if (candidates.length === 0) return;
    setPhase("saving");
    setError(null);
    try {
      const result = await saveScreenshotCandidates(
        courseId,
        candidates,
        screenshotHash,
      );
      setSaveResult(result);
      setPhase("saved");
      onSaved?.(result);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(apiErrorToState(err));
      } else if (err instanceof Error) {
        setError({ detail: err.message });
      } else {
        setError({ detail: "Save failed. Try again." });
      }
      setPhase("error");
    }
  }, [candidates, courseId, onSaved, screenshotHash]);

  return (
    <div
      ref={rootRef}
      className="flex flex-col gap-3"
      data-testid="screenshot-drop-zone"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-base font-semibold text-foreground">
          Screenshot to cards
        </h3>
        <span className="text-xs text-muted-foreground">Vision-extracted</span>
      </div>
      <p
        className="text-xs text-muted-foreground"
        data-testid="screenshot-privacy-subtitle"
      >
        Vision reads everything in the image — don&apos;t capture credentials
        or private data.
      </p>

      {/* ---------- Drop zone ---------- */}
      {(phase === "idle" || phase === "error") && (
        <div
          data-testid="screenshot-dropzone-target"
          className={`w-full h-32 border-2 border-dashed rounded-lg flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors ${
            dragging
              ? "border-brand bg-brand-muted"
              : "border-border bg-muted hover:border-brand hover:bg-brand-muted"
          }`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <ImagePlus className="size-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {dragging
              ? "Drop image here"
              : "Drop a screenshot, paste (Ctrl+V), or click"}
          </span>
        </div>
      )}

      <input
        ref={fileInputRef}
        data-testid="screenshot-file-input"
        type="file"
        accept={ACCEPT_MIME}
        className="hidden"
        onChange={handleFileInput}
      />

      {/* ---------- Uploading ---------- */}
      {phase === "uploading" && (
        <div
          data-testid="screenshot-uploading"
          className="flex items-center gap-3 px-4 py-3 bg-muted border border-border rounded-lg text-sm text-muted-foreground"
        >
          <Loader2 className="size-4 animate-spin" />
          <span>Reading screenshot…</span>
        </div>
      )}

      {/* ---------- Preview (candidate cards) ---------- */}
      {(phase === "preview" || phase === "saving") && candidates.length > 0 && (
        <div
          data-testid="screenshot-preview"
          className="flex flex-col gap-2 px-4 py-3 bg-muted border border-border rounded-lg"
        >
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Sparkles className="size-3.5" />
            <span>
              {candidates.length} card{candidates.length === 1 ? "" : "s"} ready
            </span>
          </div>
          <ul className="flex flex-col gap-2">
            {candidates.map((c, i) => (
              <li
                key={i}
                data-testid={`screenshot-candidate-${i}`}
                className="text-sm"
              >
                <p
                  className="font-medium text-foreground"
                  data-testid={`screenshot-candidate-${i}-front`}
                >
                  {truncate(c.front, 140)}
                </p>
                <p
                  className="text-xs text-muted-foreground"
                  data-testid={`screenshot-candidate-${i}-back`}
                >
                  {truncate(c.back, 200)}
                </p>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2 mt-1">
            <button
              type="button"
              data-testid="screenshot-save-all"
              onClick={save}
              disabled={phase === "saving"}
              className="h-9 px-4 bg-brand text-brand-foreground rounded-lg font-semibold text-sm hover:opacity-90 disabled:opacity-60"
            >
              {phase === "saving" ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin" />
                  Saving…
                </span>
              ) : (
                `Save all ${candidates.length} cards`
              )}
            </button>
            <button
              type="button"
              data-testid="screenshot-discard"
              onClick={reset}
              disabled={phase === "saving"}
              className="h-9 px-3 text-sm text-muted-foreground hover:text-foreground disabled:opacity-60"
            >
              Discard
            </button>
          </div>
        </div>
      )}

      {/* ---------- Saved ---------- */}
      {phase === "saved" && saveResult && (
        <div
          data-testid="screenshot-saved"
          role="status"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-emerald-300/60 bg-emerald-50/80 text-emerald-950"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold">
              Saved {saveResult.saved_count} card
              {saveResult.saved_count === 1 ? "" : "s"} to FSRS queue
            </p>
            <Link
              href={`/flashcards/due/${courseId}`}
              data-testid="screenshot-saved-link"
              className="mt-1 inline-block text-xs font-medium text-emerald-700 underline hover:text-emerald-900"
            >
              Review now
            </Link>
          </div>
          <button
            type="button"
            onClick={reset}
            className="text-xs text-emerald-700 hover:text-emerald-900"
            aria-label="Start over"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {/* ---------- Error ---------- */}
      {phase === "error" && error && (
        <div
          data-testid="screenshot-error"
          role="alert"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-red-300/60 bg-red-50/80 text-red-950"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold" data-testid="screenshot-error-detail">
              {error.detail}
            </p>
            {error.hint && (
              <p
                className="text-xs text-red-900/80"
                data-testid="screenshot-error-hint"
              >
                {error.hint}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default ScreenshotDropZone;
