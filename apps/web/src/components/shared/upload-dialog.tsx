"use client";

import { useCallback, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { uploadFile, scrapeUrl } from "@/lib/api";
import { useCourseStore } from "@/store/course";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";

interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  courseId: string;
}

export function UploadDialog({
  open,
  onOpenChange,
  courseId,
}: UploadDialogProps) {
  const t = useT();
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");
  const [dragging, setDragging] = useState(false);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);

  const processFile = useCallback(
    async (file: File) => {
      setUploading(true);
      setProgress(0);
      try {
        const result = await uploadFile(courseId, file, (pct) => setProgress(pct));
        toast.success(t("upload.uploadSuccess").replace("{name}", file.name).replace("{count}", String(result.nodes_created)));
        await fetchContentTree(courseId);
        onOpenChange(false);
      } catch (error) {
        toast.error(t("upload.uploadFailed").replace("{message}", (error as Error).message));
      } finally {
        setUploading(false);
        setProgress(0);
      }
    },
    [courseId, fetchContentTree, onOpenChange, t],
  );

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      await processFile(file);
    },
    [processFile],
  );

  const handleUrlScrape = useCallback(async () => {
    if (!url.trim()) return;

    setUploading(true);
    setUrlError("");
    try {
      const result = await scrapeUrl(courseId, url.trim());
      toast.success(t("upload.scrapeSuccess").replace("{count}", String(result.nodes_created)));
      setUrl("");
      await fetchContentTree(courseId);
      onOpenChange(false);
    } catch (error) {
      const message = (error as Error).message;
      setUrlError(message);
      toast.error(t("upload.scrapeFailed").replace("{message}", message));
    } finally {
      setUploading(false);
    }
  }, [courseId, fetchContentTree, onOpenChange, t, url]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md animate-fade-in">
        <DialogHeader>
          <DialogTitle>{t("upload.title")}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="file" className="mt-2">
          <TabsList className="w-full">
            <TabsTrigger value="file" className="flex-1">
              {t("upload.uploadFile")}
            </TabsTrigger>
            <TabsTrigger
              value="url"
              className="flex-1"
              data-testid="workspace-upload-url-tab"
            >
              {t("upload.pasteUrl")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="file" className="space-y-4 pt-4">
            <div
              role="region"
              aria-label="File drop zone"
              className={`rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
                dragging ? "border-primary bg-primary/5" : "border-border/60"
              }`}
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDragging(true);
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDragging(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDragging(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) {
                  void processFile(file);
                }
              }}
            >
              <p className={`mb-2 text-2xl ${dragging ? "text-primary" : "text-muted-foreground"}`}>
                ↑
              </p>
              <p
                className={`mb-3 text-sm ${
                  dragging ? "font-medium text-primary" : "text-muted-foreground"
                }`}
              >
                {dragging ? t("upload.dropHere") : t("upload.drag")}
              </p>
              <label>
                <input
                  data-testid="workspace-upload-file-input"
                  type="file"
                  accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
                  className="hidden"
                  onChange={(e) => void handleFileUpload(e)}
                  disabled={uploading}
                />
                <Button variant="outline" asChild disabled={uploading}>
                  <span>
                    {uploading ? (
                      <>
                        <span className="mr-1 animate-pulse">...</span>
                        {t("upload.uploading")}
                      </>
                    ) : (
                      t("upload.chooseFile")
                    )}
                  </span>
                </Button>
              </label>
              {uploading && (
                <div className="mt-3 w-full" role="status" aria-live="polite">
                  <div
                    role="progressbar"
                    aria-label={`Upload progress: ${progress}%`}
                    className="h-2.5 w-full rounded-full bg-muted overflow-hidden"
                  >
                    <div
                      className="h-full rounded-full bg-brand transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="mt-1 text-center text-xs text-muted-foreground">
                    {progress < 100 ? t("upload.uploadingProgress").replace("{pct}", String(progress)) : t("upload.processing")}
                  </p>
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="url" className="space-y-4 pt-4">
            <Input
              data-testid="workspace-upload-url-input"
              aria-label="URL to scrape"
              placeholder="https://example.com/lecture-notes"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (urlError) setUrlError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  void handleUrlScrape();
                }
              }}
              disabled={uploading}
            />
            {urlError ? (
              <p role="alert" className="text-sm text-destructive" data-testid="workspace-upload-url-error">
                {urlError}
              </p>
            ) : null}
            <Button
              data-testid="workspace-upload-url-submit"
              onClick={() => void handleUrlScrape()}
              className="w-full"
              disabled={uploading || !url.trim()}
            >
              {uploading ? (
                <>
                  <span className="mr-1 animate-pulse">...</span>
                  {t("upload.scraping")}
                </>
              ) : (
                t("upload.scrapeAndImport")
              )}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
