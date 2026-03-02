"use client";

import Image from "next/image";
import {
  useEffect,
  useRef,
  useState,
  useCallback,
  type KeyboardEvent,
  type ChangeEvent,
  type DragEvent,
  type ClipboardEvent,
} from "react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import { useCourseStore } from "@/store/course";
import { uploadFile, scrapeUrl, type ImageAttachment } from "@/lib/api";
import { getStoredAccessToken } from "@/lib/auth";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  Paperclip,
  ImagePlus,
  Link,
  SendHorizontal,
  Square,
  Loader2,
  X,
  Mic,
  MicOff,
  AudioLines,
} from "lucide-react";

const ACCEPTED_TYPES =
  ".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md,.csv,.xlsx,.xls";

const MAX_IMAGE_SIZE = 10 * 1024 * 1024; // 10MB
const MAX_IMAGES = 5;

/** Convert a File to a base64-encoded ImageAttachment. */
async function fileToImageAttachment(file: File): Promise<ImageAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip the data:...;base64, prefix
      const base64 = result.split(",")[1];
      resolve({
        data: base64,
        media_type: file.type || "image/png",
        filename: file.name,
      });
    };
    reader.onerror = () => reject(new Error("Failed to read image file"));
    reader.readAsDataURL(file);
  });
}

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
  const imageInputRef = useRef<HTMLInputElement>(null);

  // Upload / scrape state
  const [isUploading, setIsUploading] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [urlPopoverOpen, setUrlPopoverOpen] = useState(false);

  // Image attachments state
  const [pendingImages, setPendingImages] = useState<ImageAttachment[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [accessToken, setAccessToken] = useState<string | undefined>(undefined);

  // Voice recording
  const voice = useVoiceSession(courseId, { accessToken });

  const isStreaming = useChatStore((s) => s.isStreaming);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abortStream = useChatStore((s) => s.abortStream);
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);

  const isDisabled = disabled || false;
  const isBusy = isUploading || isScraping;
  const canSend = (input.trim().length > 0 || pendingImages.length > 0) && !isDisabled;

  useEffect(() => {
    const syncAccessToken = () => {
      setAccessToken(getStoredAccessToken() ?? undefined);
    };

    syncAccessToken();
    window.addEventListener("storage", syncAccessToken);
    return () => window.removeEventListener("storage", syncAccessToken);
  }, []);

  /* ── Image handling ── */
  const addImages = useCallback(async (files: File[]) => {
    const imageFiles = files.filter((f) => f.type.startsWith("image/"));
    if (imageFiles.length === 0) return;

    const remaining = MAX_IMAGES - pendingImages.length;
    if (remaining <= 0) {
      toast.error(`Maximum ${MAX_IMAGES} images allowed`);
      return;
    }
    const toProcess = imageFiles.slice(0, remaining);
    if (imageFiles.length > remaining) {
      toast.warning(`Only ${remaining} more image(s) can be added`);
    }

    for (const file of toProcess) {
      if (file.size > MAX_IMAGE_SIZE) {
        toast.error(`${file.name} exceeds 10MB limit`);
        continue;
      }
      try {
        const attachment = await fileToImageAttachment(file);
        setPendingImages((prev) => [...prev, attachment]);
      } catch {
        toast.error(`Failed to process ${file.name}`);
      }
    }
  }, [pendingImages.length]);

  const removeImage = useCallback((index: number) => {
    setPendingImages((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleImageClick = useCallback(() => {
    imageInputRef.current?.click();
  }, []);

  const handleImageChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files) void addImages(Array.from(files));
      if (imageInputRef.current) imageInputRef.current.value = "";
    },
    [addImages],
  );

  // Paste handler for images (Ctrl+V)
  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const imageFiles: File[] = [];
      for (const item of Array.from(items)) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault();
        void addImages(imageFiles);
      }
    },
    [addImages],
  );

  // Drag & drop handlers for images
  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.types.includes("Files")) {
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      const imageFiles = files.filter((f) => f.type.startsWith("image/"));
      if (imageFiles.length > 0) {
        void addImages(imageFiles);
      }
    },
    [addImages],
  );

  /* ── Send message ── */
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text && pendingImages.length === 0) return;
    const images = pendingImages.length > 0 ? [...pendingImages] : undefined;
    setInput("");
    setPendingImages([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await sendMessage(courseId, text || "(image)", {
      activeTab: activeSection,
      images,
    });
  }, [input, pendingImages, courseId, sendMessage, activeSection]);

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
    <div
      className={cn(
        "shrink-0 border-t bg-background px-3 py-2",
        isDragOver && "ring-2 ring-primary ring-inset bg-primary/5",
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Hidden file inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        multiple
        className="hidden"
        aria-label="Upload files"
        onChange={(e) => void handleFileChange(e)}
      />
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        aria-label="Attach images"
        onChange={handleImageChange}
      />

      {/* Image preview strip */}
      {pendingImages.length > 0 && (
        <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
          {pendingImages.map((img, i) => (
            <div
              key={`${img.filename ?? "img"}-${i}`}
              className="relative shrink-0 group"
            >
              <Image
                src={`data:${img.media_type};base64,${img.data}`}
                alt={img.filename ?? `Image ${i + 1}`}
                width={64}
                height={64}
                unoptimized
                className="h-16 w-16 rounded-md object-cover border"
              />
              <button
                type="button"
                onClick={() => removeImage(i)}
                className="absolute -top-1.5 -right-1.5 rounded-full bg-destructive text-destructive-foreground p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label="Remove image"
              >
                <X className="size-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-end gap-1.5">
        {/* File upload button */}
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="mb-0.5 text-muted-foreground hover:text-foreground"
          title="Attach file"
          aria-label="Upload files"
          disabled={isDisabled || isStreaming || isBusy}
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
            pendingImages.length > 0 && "text-primary",
          )}
          title="Attach image"
          aria-label="Attach images"
          disabled={isDisabled || isStreaming || isBusy || pendingImages.length >= MAX_IMAGES}
          onClick={handleImageClick}
        >
          <ImagePlus className="size-4" />
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
          data-testid="chat-input"
          data-chat-input
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={pendingImages.length > 0 ? "Add a message about these images..." : "Ask anything..."}
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

        {/* Voice recording button */}
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className={cn(
            "mb-0.5 text-muted-foreground hover:text-foreground",
            voice.voiceState === "recording" && "text-red-500 animate-pulse",
            voice.voiceState === "processing" && "text-amber-500",
            voice.voiceState === "playing" && "text-green-500",
          )}
          title={
            voice.voiceState === "recording"
              ? "Stop recording"
              : voice.voiceState === "processing"
                ? "Processing..."
                : "Voice input"
          }
          aria-label="Voice input"
          disabled={isDisabled || isStreaming || isBusy || voice.voiceState === "processing" || voice.voiceState === "playing"}
          onClick={() => {
            if (voice.voiceState === "recording") {
              voice.stopRecording();
            } else {
              void voice.startRecording();
            }
          }}
        >
          {voice.voiceState === "recording" ? (
            <MicOff className="size-4" />
          ) : voice.voiceState === "processing" ? (
            <Loader2 className="size-4 animate-spin" />
          ) : voice.voiceState === "playing" ? (
            <AudioLines className="size-4" />
          ) : (
            <Mic className="size-4" />
          )}
        </Button>

        {/* Send / Stop button */}
        {isStreaming ? (
          <Button
            type="button"
            variant="destructive"
            size="icon-xs"
            className="mb-0.5"
            data-testid="chat-stop"
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
            data-testid="chat-send"
            onClick={() => void handleSend()}
            disabled={!canSend}
            title="Send message"
          >
            <SendHorizontal className="size-3.5" />
          </Button>
        )}
      </div>

      {/* Voice status indicator */}
      {voice.voiceState !== "idle" && (
        <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
          {voice.voiceState === "recording" && (
            <>
              <span className="inline-block size-2 rounded-full bg-red-500 animate-pulse" />
              <span>Recording... click mic to stop</span>
            </>
          )}
          {voice.voiceState === "processing" && (
            <>
              <Loader2 className="size-3 animate-spin" />
              <span>{voice.transcript ? `"${voice.transcript}"` : "Processing audio..."}</span>
            </>
          )}
          {voice.voiceState === "playing" && (
            <>
              <AudioLines className="size-3 text-green-500" />
              <span>Playing response...</span>
            </>
          )}
          {voice.error && (
            <span className="text-destructive">{voice.error}</span>
          )}
        </div>
      )}
    </div>
  );
}
