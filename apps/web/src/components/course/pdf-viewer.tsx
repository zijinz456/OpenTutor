"use client";

import { File } from "lucide-react";

interface PdfViewerProps {
  fileName?: string;
}

export function PdfViewer({ fileName }: PdfViewerProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="border-b px-3 py-2 flex items-center gap-2 shrink-0 bg-gray-50">
        <File className="w-3.5 h-3.5 text-red-500" />
        <span className="text-xs font-medium text-gray-900 truncate">
          {fileName || "No file selected"}
        </span>
      </div>
      <div className="flex-1 bg-gray-100 p-5 flex flex-col gap-3.5 overflow-y-auto">
        {fileName ? (
          <>
            <span className="text-[11px] font-medium text-gray-400 text-center">
              PDF Preview
            </span>
            <div className="flex-1 bg-white p-5 border border-gray-200 rounded flex flex-col gap-3 overflow-y-auto">
              <p className="text-xs text-gray-500 leading-relaxed">
                Upload a PDF to view its contents here. The AI will generate notes
                from this material in the Notes panel.
              </p>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <File className="w-10 h-10 mx-auto text-gray-300 mb-3" />
              <p className="text-sm text-gray-400">No document loaded</p>
              <p className="text-xs text-gray-300 mt-1">Upload a file to preview it here</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
