"use client";

import { useRef, useCallback, useState, type ChangeEvent } from "react";
import { Button } from "@/components/ui/button";
import { uploadFile } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Paperclip, ImagePlus, Loader2 } from "lucide-react";
import { ACCEPTED_FILE_TYPES, MAX_IMAGES } from "@/components/chat/chat-input-utils";
import { UrlScrapePopover } from "@/components/chat/url-scrape-popover";

interface AttachmentButtonsProps {
  courseId: string;
  disabled: boolean;
  pendingImageCount: number;
  onImageClick: () => void;
  onFilesUploaded: () => void;
}

/**
 * Row of attachment buttons: file upload, image attach, and URL scrape.
 * File upload logic is self-contained here; URL scrape is delegated
 * to UrlScrapePopover.
 */
export function AttachmentButtons({
  courseId,
  disabled,
  pendingImageCount,
  onImageClick,
  onFilesUploaded,
}: AttachmentButtonsProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isScraping, setIsScraping] = useState(false);

  const isBusy = isUploading || isScraping;

  const handleFileClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      setIsUploading(true);
      let successCount = 0;

      for (const file of Array.from(files)) {
        try {
          await uploadFile(courseId, file);
          successCount++;
        } catch (err: unknown) {
          const msg =
            err instanceof Error ? err.message : "Upload failed";
          toast.error(`Failed to upload ${file.name}: ${msg}`);
        }
      }

      // Reset file input so the same file can be re-selected
      if (fileInputRef.current) fileInputRef.current.value = "";
      setIsUploading(false);

      if (successCount > 0) {
        toast.success(
          `Uploaded ${successCount} file${successCount > 1 ? "s" : ""}`,
        );
        onFilesUploaded();
      }
    },
    [courseId, onFilesUploaded],
  );

  return (
    <>
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_FILE_TYPES}
        multiple
        className="hidden"
        aria-label="Upload files"
        onChange={(e) => void handleFileChange(e)}
      />

      {/* File upload button */}
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className="mb-0.5 text-muted-foreground hover:text-foreground"
        title="Attach file"
        aria-label="Upload files"
        disabled={disabled || isBusy}
        onClick={handleFileClick}
      >
        {isUploading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Paperclip className="size-4" />
        )}
      </Button>

      {/* Image upload button */}
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        className={cn(
          "mb-0.5 text-muted-foreground hover:text-foreground",
          pendingImageCount > 0 && "text-primary",
        )}
        title="Attach image"
        aria-label="Attach images"
        disabled={disabled || isBusy || pendingImageCount >= MAX_IMAGES}
        onClick={onImageClick}
      >
        <ImagePlus className="size-4" />
      </Button>

      {/* URL scrape button with popover */}
      <UrlScrapePopover
        courseId={courseId}
        disabled={disabled || isBusy}
        onScraped={onFilesUploaded}
        onScrapingChange={setIsScraping}
      />
    </>
  );
}
