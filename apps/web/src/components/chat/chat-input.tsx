"use client";

import {
  useRef,
  useState,
  useCallback,
  type KeyboardEvent,
  type ChangeEvent,
} from "react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { useChatStore } from "@/store/chat";
import { useSceneStore } from "@/store/scene";
import { useWorkspaceStore } from "@/store/workspace";
import { useCourseStore } from "@/store/course";
import { uploadFile, scrapeUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  Paperclip,
  Link,
  SendHorizontal,
  Square,
  Loader2,
  X,
} from "lucide-react";

const ACCEPTED_TYPES =
  ".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md,.csv,.xlsx,.xls";

interface ChatInputProps {
  courseId: string;
  disabled?: boolean;
}

/**
 * Chat input bar with auto-growing textarea, send/stop button,
 * file upload, and URL scrape.
 *
 * - Enter sends; Shift+Enter inserts newline.
 * - While streaming, the send button becomes a stop button.
 * - 📎 opens a file picker; selected files are uploaded via API.
 * - 🔗 opens a popover for entering a URL to scrape.
 */
export function ChatInput({ courseId, disabled }: ChatInputProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Upload / scrape state
  const [isUploading, setIsUploading] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [urlPopoverOpen, setUrlPopoverOpen] = useState(false);

  const isStreaming = useChatStore((s) => s.isStreaming);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abortStream = useChatStore((s) => s.abortStream);
  const activeScene = useSceneStore((s) => s.activeScene);
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);

  const isDisabled = disabled || false;
  const isBusy = isUploading || isScraping;
  const canSend = input.trim().length > 0 && !isDisabled;

  /* ── Send message ── */
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await sendMessage(courseId, text, {
      scene: activeScene,
      activeTab: activeSection,
    });
  }, [input, courseId, sendMessage, activeScene, activeSection]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (canSend && !isStreaming) {
          void handleSend();
        }
      }
    },
    [canSend, isStreaming, handleSend],
  );

  // Auto-grow textarea up to 4 rows (~96px).
  const handleInput = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      const el = e.target;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
    },
    [],
  );

  /* ── File upload ── */
  const handleFileClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;

      setIsUploading(true);
      let successCount = 0;
      let failCount = 0;

      for (const file of Array.from(files)) {
        try {
          await uploadFile(courseId, file);
          successCount++;
        } catch (err: unknown) {
          failCount++;
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
        // Refresh the course content tree + file list
        void fetchContentTree(courseId);
        void fetchIngestionJobs(courseId);
      }
    },
    [courseId, fetchContentTree, fetchIngestionJobs],
  );

  /* ── URL scrape ── */
  const handleUrlSubmit = useCallback(async () => {
    const url = urlInput.trim();
    if (!url) return;

    // Basic URL validation
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      toast.error("Please enter a valid URL starting with http:// or https://");
      return;
    }

    setIsScraping(true);
    try {
      await scrapeUrl(courseId, url);
      toast.success("URL content added successfully");
      setUrlInput("");
      setUrlPopoverOpen(false);
      // Refresh the course content tree + file list
      void fetchContentTree(courseId);
      void fetchIngestionJobs(courseId);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Scrape failed";
      toast.error(`Failed to scrape URL: ${msg}`);
    } finally {
      setIsScraping(false);
    }
  }, [urlInput, courseId, fetchContentTree, fetchIngestionJobs]);

  const handleUrlKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        void handleUrlSubmit();
      }
      if (e.key === "Escape") {
        setUrlPopoverOpen(false);
      }
    },
    [handleUrlSubmit],
  );

  return (
    <div className="shrink-0 border-t bg-background px-3 py-2">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        multiple
        className="hidden"
        aria-label="Upload files"
        onChange={(e) => void handleFileChange(e)}
      />

      <div className="flex items-end gap-1.5">
        {/* File upload button */}
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="mb-0.5 text-muted-foreground hover:text-foreground"
          title="Attach file"
          disabled={isDisabled || isStreaming || isBusy}
          onClick={handleFileClick}
        >
          {isUploading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Paperclip className="size-4" />
          )}
        </Button>

        {/* URL paste button with popover */}
        <Popover open={urlPopoverOpen} onOpenChange={setUrlPopoverOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="mb-0.5 text-muted-foreground hover:text-foreground"
              title="Add URL"
              disabled={isDisabled || isStreaming || isBusy}
            >
              {isScraping ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Link className="size-4" />
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent
            side="top"
            align="start"
            className="w-80 p-3"
          >
            <p className="mb-2 text-xs font-medium text-foreground">
              Add URL to course
            </p>
            <div className="flex items-center gap-1.5">
              <input
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={handleUrlKeyDown}
                placeholder="https://example.com/lecture-notes"
                disabled={isScraping}
                className={cn(
                  "flex-1 rounded-md border bg-transparent px-2.5 py-1.5 text-sm",
                  "placeholder:text-muted-foreground",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                )}
                autoFocus
              />
              <Button
                type="button"
                size="sm"
                className="h-8 px-3 text-xs"
                disabled={!urlInput.trim() || isScraping}
                onClick={() => void handleUrlSubmit()}
              >
                {isScraping ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  "Add"
                )}
              </Button>
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              The URL content will be scraped and added to your course materials.
            </p>
          </PopoverContent>
        </Popover>

        {/* Auto-growing textarea */}
        <textarea
          ref={textareaRef}
          data-chat-input
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything..."
          rows={1}
          disabled={isDisabled}
          className={cn(
            "flex-1 resize-none rounded-md border bg-transparent px-3 py-1.5 text-sm",
            "placeholder:text-muted-foreground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "min-h-[32px] max-h-[96px]",
          )}
        />

        {/* Send / Stop button */}
        {isStreaming ? (
          <Button
            type="button"
            variant="destructive"
            size="icon-xs"
            className="mb-0.5"
            onClick={abortStream}
            title="Stop generating"
          >
            <Square className="size-3" />
          </Button>
        ) : (
          <Button
            type="button"
            variant="default"
            size="icon-xs"
            className="mb-0.5"
            onClick={() => void handleSend()}
            disabled={!canSend}
            title="Send message"
          >
            <SendHorizontal className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}
