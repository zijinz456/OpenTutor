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

interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  courseId: string;
}

export function UploadDialog({ open, onOpenChange, courseId }: UploadDialogProps) {
  const [uploading, setUploading] = useState(false);
  const [url, setUrl] = useState("");
  const { fetchContentTree } = useCourseStore();

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

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

  const handleUrlScrape = async () => {
    if (!url.trim()) return;

    setUploading(true);
    try {
      const result = await scrapeUrl(courseId, url.trim());
      toast.success(`Scraped URL: ${result.nodes_created} sections created`);
      setUrl("");
      await fetchContentTree(courseId);
      onOpenChange(false);
    } catch (err) {
      toast.error(`Scrape failed: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add Learning Materials</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="file" className="mt-2">
          <TabsList className="w-full">
            <TabsTrigger value="file" className="flex-1">
              <FileUp className="h-4 w-4 mr-1" />
              Upload File
            </TabsTrigger>
            <TabsTrigger value="url" className="flex-1">
              <Link className="h-4 w-4 mr-1" />
              Paste URL
            </TabsTrigger>
          </TabsList>

          <TabsContent value="file" className="space-y-4 pt-4">
            <div className="border-2 border-dashed rounded-lg p-8 text-center">
              <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground mb-3">
                Drag & drop a PDF here, or click to browse
              </p>
              <label>
                <input
                  type="file"
                  accept=".pdf"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={uploading}
                />
                <Button variant="outline" asChild disabled={uploading}>
                  <span>
                    {uploading ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        Parsing...
                      </>
                    ) : (
                      "Choose PDF"
                    )}
                  </span>
                </Button>
              </label>
            </div>
          </TabsContent>

          <TabsContent value="url" className="space-y-4 pt-4">
            <Input
              placeholder="https://example.com/lecture-notes"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleUrlScrape()}
              disabled={uploading}
            />
            <Button
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
