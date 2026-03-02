"use client";

import { useState, useCallback } from "react";
import { Upload, Link, FileUp, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

export function UploadDialog({ open, onOpenChange, courseId }: UploadDialogProps) {
  const t = useT();
  const [uploading, setUploading] = useState(false);
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");
  const [dragging, setDragging] = useState(false);
  const { fetchContentTree } = useCourseStore();

  const processFile = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const result = await uploadFile(courseId, file);
        toast.success(`Uploaded ${file.name}: ${result.nodes_created} sections created`);
        await fetchContentTree(courseId);
        onOpenChange(false);
      } catch (err) {
        toast.error(`Upload failed: ${(err as Error).message}`);
      } finally {
        setUploading(false);
      }
    },
    [courseId, fetchContentTree, onOpenChange],
  );

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      await processFile(file);
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
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (!file) return;
      await processFile(file);
    },
    [processFile],
  );

  const handleUrlScrape = async () => {
    if (!url.trim()) return;

    setUploading(true);
    setUrlError("");
    try {
      const result = await scrapeUrl(courseId, url.trim());
      toast.success(`Scraped URL: ${result.nodes_created} sections created`);
      setUrl("");
      setUrlError("");
      await fetchContentTree(courseId);
      onOpenChange(false);
    } catch (err) {
      const message = (err as Error).message;
      setUrlError(message);
      toast.error(`Scrape failed: ${message}`);
    } finally {
      setUploading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("upload.title")}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="file" className="mt-2">
          <TabsList className="w-full">
            <TabsTrigger value="file" className="flex-1">
              <FileUp className="h-4 w-4 mr-1" />
              Upload File
            </TabsTrigger>
            <TabsTrigger value="url" className="flex-1" data-testid="workspace-upload-url-tab">
              <Link className="h-4 w-4 mr-1" />
              Paste URL
            </TabsTrigger>
          </TabsList>

          <TabsContent value="file" className="space-y-4 pt-4">
            <div
              className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                dragging
                  ? "border-primary bg-primary/5"
                  : "border-border"
              }`}
              onDragOver={handleDragOver}
              onDragEnter={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <Upload className={`h-8 w-8 mx-auto mb-2 ${dragging ? "text-primary" : "text-muted-foreground"}`} />
              <p className={`text-sm mb-3 ${dragging ? "text-primary font-medium" : "text-muted-foreground"}`}>
                {dragging ? "Drop file here" : t("upload.drag")}
              </p>
              <label>
                <input
                  data-testid="workspace-upload-file-input"
                  type="file"
                  accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={uploading}
                />
                <Button variant="outline" asChild disabled={uploading}>
                  <span>
                    {uploading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        {t("upload.uploading")}
                      </>
                    ) : (
                      "Choose File"
                    )}
                  </span>
                </Button>
              </label>
            </div>
          </TabsContent>

          <TabsContent value="url" className="space-y-4 pt-4">
            <Input
              data-testid="workspace-upload-url-input"
              placeholder="https://example.com/lecture-notes"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                if (urlError) setUrlError("");
              }}
              onKeyDown={(e) => e.key === "Enter" && handleUrlScrape()}
              disabled={uploading}
            />
            {urlError ? (
              <p className="text-sm text-destructive" data-testid="workspace-upload-url-error">
                {urlError}
              </p>
            ) : null}
            <Button
              data-testid="workspace-upload-url-submit"
              onClick={handleUrlScrape}
              className="w-full"
              disabled={uploading || !url.trim()}
            >
              {uploading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  Scraping...
                </>
              ) : (
                "Scrape & Import"
              )}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
