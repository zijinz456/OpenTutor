"use client";

import { useCallback, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

interface PdfViewerProps {
  fileUrl?: string;
  fileName?: string;
}

export function PdfViewer({ fileUrl, fileName }: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.0);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setPageNumber(1);
  }, []);

  const goToPrev = () => setPageNumber((p) => Math.max(1, p - 1));
  const goToNext = () => setPageNumber((p) => Math.min(numPages, p + 1));
  const zoomIn = () => setScale((s) => Math.min(2.5, s + 0.2));
  const zoomOut = () => setScale((s) => Math.max(0.4, s - 0.2));

  if (!fileUrl) {
    return (
      <div className="h-full flex flex-col">
        <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-muted">
          <span className="text-xs font-medium text-foreground truncate">
            {fileName || "No file selected"}
          </span>
        </div>
        <div className="flex-1 flex items-center justify-center bg-muted/60">
          <div className="text-center">
            <p className="text-sm text-muted-foreground">No document loaded</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Upload a PDF to preview it here</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="border-b px-3 py-1.5 flex items-center gap-2 shrink-0 bg-muted">
        <span className="text-xs font-medium text-foreground truncate flex-1">
          {fileName || "Document"}
        </span>

        <div className="flex items-center gap-1">
          <button type="button" onClick={zoomOut} className="p-1 rounded hover:bg-muted-foreground/10" title="Zoom out">
            <span className="text-xs text-muted-foreground font-bold">{"\u2212"}</span>
          </button>
          <span className="text-[10px] text-muted-foreground w-8 text-center">{Math.round(scale * 100)}%</span>
          <button type="button" onClick={zoomIn} className="p-1 rounded hover:bg-muted-foreground/10" title="Zoom in">
            <span className="text-xs text-muted-foreground font-bold">+</span>
          </button>
        </div>

        <div className="flex items-center gap-1 ml-1">
          <button type="button" onClick={goToPrev} disabled={pageNumber <= 1} className="p-1 rounded hover:bg-muted-foreground/10 disabled:opacity-30" title="Previous page">
            <span className="text-xs text-muted-foreground">{"\u2039"}</span>
          </button>
          <span className="text-[10px] text-muted-foreground whitespace-nowrap">
            {pageNumber} / {numPages || "?"}
          </span>
          <button type="button" onClick={goToNext} disabled={pageNumber >= numPages} className="p-1 rounded hover:bg-muted-foreground/10 disabled:opacity-30" title="Next page">
            <span className="text-xs text-muted-foreground">{"\u203A"}</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-muted/60 flex justify-center p-4">
        <Document
          file={fileUrl}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={
            <div className="flex items-center justify-center h-40">
              <span className="text-sm animate-pulse text-muted-foreground">Loading...</span>
            </div>
          }
          error={
            <div className="text-center py-8">
              <p className="text-sm text-destructive">Failed to load PDF</p>
              <p className="text-xs text-muted-foreground mt-1">The file may be corrupted or inaccessible</p>
            </div>
          }
        >
          <Page
            pageNumber={pageNumber}
            scale={scale}
            renderTextLayer
            renderAnnotationLayer
          />
        </Document>
      </div>
    </div>
  );
}
