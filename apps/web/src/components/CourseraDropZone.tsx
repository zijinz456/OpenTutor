"use client";

/**
 * Coursera ZIP drop zone (Phase 14 T7).
 *
 * Drop a .zip → preview filename + size → click Import → POST to
 * `/content/upload/coursera` → render summary / already-imported / error.
 *
 * ADHD copy: short, no guilt, no "Are you sure?" modals. Errors show the
 * backend's structured hint so the user knows what to fix instead of
 * re-rolling blindly.
 */

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { Loader2, UploadCloud, CheckCircle2, Info, AlertCircle, X } from "lucide-react";
import { uploadCoursera, parseCourseraErrorDetail, ApiError } from "@/lib/api/coursera";
import type { CourseraUploadResponse } from "@/lib/api/coursera";

interface Props {
  courseId: string;
  onSuccess?: (response: CourseraUploadResponse) => void;
}

type Phase = "idle" | "preview" | "uploading" | "success" | "already" | "error";

interface ErrorState {
  detail: string;
  reason?: string;
  hint?: string;
}

/** Human-readable MB size (e.g. "42.5 MB"). Pure, easy to assert in tests. */
function formatMB(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}

export function CourseraDropZone({ courseId, onSuccess }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [dragging, setDragging] = useState(false);
  const [response, setResponse] = useState<CourseraUploadResponse | null>(null);
  const [error, setError] = useState<ErrorState | null>(null);

  const acceptFile = useCallback((f: File) => {
    // Only .zip — silently ignore anything else rather than showing a
    // red error, since drag-n-drop can easily pick up stray desktop files.
    if (!f.name.toLowerCase().endsWith(".zip")) return;
    setFile(f);
    setPhase("preview");
    setError(null);
    setResponse(null);
  }, []);

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const picked = e.target.files?.[0];
      if (picked) acceptFile(picked);
      e.target.value = "";
    },
    [acceptFile],
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
      if (dropped) acceptFile(dropped);
    },
    [acceptFile],
  );

  const clearFile = useCallback(() => {
    setFile(null);
    setPhase("idle");
    setError(null);
    setResponse(null);
  }, []);

  const submit = useCallback(async () => {
    if (!file) return;
    setPhase("uploading");
    setError(null);
    try {
      const res = await uploadCoursera(courseId, file);
      setResponse(res);
      setPhase(res.status === "already_imported" ? "already" : "success");
      onSuccess?.(res);
    } catch (err) {
      // Structured 400 from `CourseraAdapterError`: "<reason>. Hint: <hint>"
      if (err instanceof ApiError) {
        const parsed = parseCourseraErrorDetail(err.detail ?? err.message);
        setError(parsed);
      } else if (err instanceof Error) {
        setError({ detail: err.message });
      } else {
        setError({ detail: "Upload failed. Try again." });
      }
      setPhase("error");
    }
  }, [courseId, file, onSuccess]);

  return (
    <div
      className="flex flex-col gap-3"
      data-testid="coursera-drop-zone"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-base font-semibold text-foreground">
          Coursera import (ZIP)
        </h3>
        <span className="text-xs text-muted-foreground">
          VTT transcripts + PDF slides
        </span>
      </div>

      {/* ---------- Drop zone ---------- */}
      {(phase === "idle" || phase === "error") && (
        <div
          data-testid="coursera-dropzone-target"
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
          <UploadCloud className="size-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {dragging ? "Drop ZIP here" : "Drop a Coursera .zip or click to pick"}
          </span>
        </div>
      )}

      <input
        ref={fileInputRef}
        data-testid="coursera-file-input"
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={handleFileInput}
      />

      {/* ---------- Preview ---------- */}
      {(phase === "preview" || phase === "uploading") && file && (
        <div
          data-testid="coursera-preview"
          className="flex items-center gap-3 px-4 py-3 bg-muted border border-border rounded-lg"
        >
          <UploadCloud className="size-4 shrink-0 text-muted-foreground" />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground truncate" data-testid="coursera-preview-name">
              {file.name}
            </p>
            <p className="text-xs text-muted-foreground" data-testid="coursera-preview-size">
              {formatMB(file.size)}
            </p>
          </div>
          {phase === "preview" && (
            <>
              <button
                type="button"
                data-testid="coursera-clear"
                onClick={clearFile}
                className="text-xs text-muted-foreground hover:text-foreground"
                aria-label="Remove file"
              >
                <X className="size-4" />
              </button>
              <button
                type="button"
                data-testid="coursera-import"
                onClick={submit}
                className="h-9 px-4 bg-brand text-brand-foreground rounded-lg font-semibold text-sm hover:opacity-90"
              >
                Import course
              </button>
            </>
          )}
          {phase === "uploading" && (
            <div
              data-testid="coursera-uploading"
              className="flex items-center gap-2 text-sm text-muted-foreground"
            >
              <Loader2 className="size-4 animate-spin" />
              <span>Importing...</span>
            </div>
          )}
        </div>
      )}

      {/* ---------- Success ---------- */}
      {phase === "success" && response && (
        <div
          data-testid="coursera-success"
          role="status"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-emerald-300/60 bg-emerald-50/80 text-emerald-950"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold">
              Imported {response.lectures_total} lecture{response.lectures_total === 1 ? "" : "s"}
              {" "}
              ({response.lectures_paired} paired)
            </p>
            <p className="text-xs text-emerald-900/80">
              VTT-only: {response.lectures_vtt_only} / PDF-only: {response.lectures_pdf_only}
            </p>
            <Link
              href={`/course/${response.course_id}`}
              data-testid="coursera-view-roadmap"
              className="mt-2 inline-block text-xs font-medium text-emerald-700 underline hover:text-emerald-900"
            >
              View roadmap
            </Link>
          </div>
          <button
            type="button"
            onClick={clearFile}
            className="text-xs text-emerald-700 hover:text-emerald-900"
            aria-label="Start over"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {/* ---------- Already imported ---------- */}
      {phase === "already" && response && (
        <div
          data-testid="coursera-already"
          role="status"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-blue-200/60 bg-blue-50/70 text-blue-950"
        >
          <Info className="mt-0.5 size-4 shrink-0 text-blue-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold">This ZIP was already imported</p>
            <p className="text-xs text-blue-900/80">
              {response.lectures_total} lecture{response.lectures_total === 1 ? "" : "s"} already live in this course — no new jobs created.
            </p>
            <Link
              href={`/course/${response.course_id}`}
              data-testid="coursera-view-roadmap"
              className="mt-2 inline-block text-xs font-medium text-blue-700 underline hover:text-blue-900"
            >
              View roadmap
            </Link>
          </div>
          <button
            type="button"
            onClick={clearFile}
            className="text-xs text-blue-700 hover:text-blue-900"
            aria-label="Start over"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {/* ---------- Error ---------- */}
      {phase === "error" && error && (
        <div
          data-testid="coursera-error"
          role="alert"
          className="flex items-start gap-3 px-4 py-3 rounded-lg border border-red-300/60 bg-red-50/80 text-red-950"
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-red-600" />
          <div className="flex-1 min-w-0 text-sm">
            <p className="font-semibold" data-testid="coursera-error-detail">
              {error.reason ?? error.detail}
            </p>
            {error.hint && (
              <p className="text-xs text-red-900/80" data-testid="coursera-error-hint">
                {error.hint}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default CourseraDropZone;
