"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore } from "@/store/workspace";
import { getFileUrl } from "@/lib/api";
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
  void courseId;

  const fileUrl = useMemo(
    () => (pdfOverlay ? getFileUrl(pdfOverlay.fileId) : null),
    [pdfOverlay],
  );

  if (!pdfOverlay || !fileUrl) {
    return null;
  }

  return (
    <div
      className="flex-1 flex flex-col overflow-hidden"
      data-testid="pdf-viewer-overlay"
    >
      {/* Header */}
      <div className="px-3 py-1.5 border-b border-border/60 flex items-center gap-2 shrink-0 glass">
        <FileText className="size-3.5 text-muted-foreground shrink-0" />
        <span className="text-xs font-medium truncate flex-1">
          {pdfOverlay.fileName}
        </span>

        <a
          href={fileUrl}
          download={pdfOverlay.fileName}
          className="inline-flex"
          title="Download"
        >
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
            <Download className="size-3.5" />
          </Button>
        </a>

        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={closePdf}
          title={t("general.close")}
        >
          <X className="size-3.5" />
        </Button>
      </div>

      {/* PDF embed */}
      <div className="flex-1 relative bg-muted/30">
        <iframe
          src={fileUrl}
          title={pdfOverlay.fileName}
          className="absolute inset-0 w-full h-full border-none"
        />

        {/* Fallback message (visible only when iframe fails to load) */}
        <noscript>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="text-sm text-muted-foreground mb-2">
                Unable to display PDF inline.
              </p>
              <a
                href={fileUrl}
                download={pdfOverlay.fileName}
                className="text-sm text-primary underline"
              >
                Download {pdfOverlay.fileName}
              </a>
            </div>
          </div>
        </noscript>
      </div>
    </div>
  );
}
