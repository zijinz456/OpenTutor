"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore } from "@/store/workspace";
import { downloadCourseFile } from "@/lib/api";
import { trackApiFailure } from "@/lib/error-telemetry";
import { useT } from "@/lib/i18n-context";
import { X, Download, FileText } from "lucide-react";

interface PdfViewerOverlayProps {
  courseId: string;
}

/**
 * PDF viewer overlay.
 *
 * Shown instead of the active section when pdfOverlay is set in the workspace
 * store. Embeds the PDF in an iframe and provides a close button + download
 * fallback link.
 */
export function PdfViewerOverlay({ courseId }: PdfViewerOverlayProps) {
  const t = useT();
  const pdfOverlay = useWorkspaceStore((s) => s.pdfOverlay);
  const closePdf = useWorkspaceStore((s) => s.closePdf);
  const currentUrlRef = useRef<string | null>(null);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [downloadName, setDownloadName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const releaseCurrentUrl = useCallback(() => {
    if (currentUrlRef.current) {
      URL.revokeObjectURL(currentUrlRef.current);
      currentUrlRef.current = null;
    }
    setFileUrl(null);
  }, []);

  const loadPdf = useCallback(async () => {
    if (!pdfOverlay) return;
    setLoading(true);
    setError(null);
    try {
      const result = await downloadCourseFile(pdfOverlay.fileId);
      const nextUrl = URL.createObjectURL(result.blob);
      if (currentUrlRef.current) {
        URL.revokeObjectURL(currentUrlRef.current);
      }
      currentUrlRef.current = nextUrl;
      setFileUrl(nextUrl);
      setDownloadName(result.fileName || pdfOverlay.fileName);
    } catch (err) {
      trackApiFailure("download", err, {
        endpoint: `/content/files/${pdfOverlay.fileId}`,
        courseId,
      });
      setError(err instanceof Error ? err.message : t("pdf.loadFailed"));
      releaseCurrentUrl();
    } finally {
      setLoading(false);
    }
  }, [courseId, pdfOverlay, releaseCurrentUrl, t]);

  useEffect(() => {
    if (!pdfOverlay) {
      releaseCurrentUrl();
      setDownloadName(null);
      setError(null);
      setLoading(false);
      return;
    }
    void loadPdf();
  }, [loadPdf, pdfOverlay, reloadTick, releaseCurrentUrl]);

  useEffect(() => {
    return () => {
      if (currentUrlRef.current) {
        URL.revokeObjectURL(currentUrlRef.current);
      }
    };
  }, []);

  if (!pdfOverlay) {
    return null;
  }

  return (
    <div
      role="document"
      aria-label={`PDF viewer: ${pdfOverlay.fileName}`}
      className="flex-1 flex flex-col overflow-hidden"
      data-testid="pdf-viewer-overlay"
    >
      {/* Header */}
      <div className="px-3 py-1.5 border-b border-border/60 flex items-center gap-2 shrink-0 glass">
        <FileText className="size-3.5 text-muted-foreground shrink-0" aria-hidden="true" />
        <span className="text-xs font-medium truncate flex-1">
          {pdfOverlay.fileName}
        </span>

        {fileUrl ? (
          <a
            href={fileUrl}
            download={downloadName || pdfOverlay.fileName}
            className="inline-flex"
            title="Download"
            aria-label={`Download ${downloadName || pdfOverlay.fileName}`}
          >
            <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
              <Download className="size-3.5" aria-hidden="true" />
            </Button>
          </a>
        ) : (
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0" disabled title="Download">
            <Download className="size-3.5" aria-hidden="true" />
          </Button>
        )}

        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={closePdf}
          title={t("general.close")}
          aria-label="Close PDF viewer"
        >
          <X className="size-3.5" />
        </Button>
      </div>

      {/* PDF embed */}
      <div className="flex-1 relative bg-muted/30">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            {t("pdf.loading")}
          </div>
        ) : null}

        {!loading && error ? (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div className="text-center space-y-3 max-w-md">
              <p className="text-sm text-destructive">{error}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setReloadTick((value) => value + 1)}
              >
                {t("pdf.retry")}
              </Button>
            </div>
          </div>
        ) : null}

        {!loading && !error && fileUrl ? (
          <iframe
            src={fileUrl}
            title={pdfOverlay.fileName}
            className="absolute inset-0 w-full h-full border-none"
          />
        ) : null}

        {/* Fallback message (visible only when iframe fails to load) */}
        <noscript>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-muted-foreground mb-2">
                Unable to display PDF inline.
              </p>
              {fileUrl ? (
                <a
                  href={fileUrl}
                  download={downloadName || pdfOverlay.fileName}
                  className="text-sm text-primary underline"
                >
                  Download {downloadName || pdfOverlay.fileName}
                </a>
              ) : null}
            </div>
          </div>
        </noscript>
      </div>
    </div>
  );
}
