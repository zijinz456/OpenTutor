"use client";

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  type KeyboardEvent,
  type ChangeEvent,
} from "react";
import { useChatStore } from "@/store/chat";
import { useWorkspaceStore } from "@/store/workspace";
import { useCourseStore } from "@/store/course";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n-context";
import { useImageAttachments } from "@/components/chat/use-image-attachments";
import { ImagePreviewStrip } from "@/components/chat/image-preview-strip";
import { AttachmentButtons } from "@/components/chat/attachment-buttons";
import { SendButton } from "@/components/chat/send-button";

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
 * - Attachment buttons handle file upload, image attach, and URL scrape.
 */
export function ChatInput({ courseId, disabled }: ChatInputProps) {
  const t = useT();
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Image attachments (add, remove, drag-drop, paste)
  const {
    clearImages,
    handleDragLeave,
    handleDragOver,
    handleDrop,
    handleImageChange,
    handleImageClick,
    handlePaste,
    imageInputRef,
    isDragOver,
    pendingImages,
    removeImage,
  } = useImageAttachments();

  const isStreaming = useChatStore((s) => s.isStreaming);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abortStream = useChatStore((s) => s.abortStream);
  const activeSection = useWorkspaceStore((s) => s.activeSection);
  const fetchContentTree = useCourseStore((s) => s.fetchContentTree);
  const fetchIngestionJobs = useCourseStore((s) => s.fetchIngestionJobs);

  const isDisabled = disabled || false;
  const canSend = (input.trim().length > 0 || pendingImages.length > 0) && !isDisabled;

  // Virtual keyboard avoidance — keep input visible on iOS Safari
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    let rafId: number | null = null;
    const onResize = () => {
      const el = textareaRef.current;
      if (!el) return;
      // When viewport height shrinks (keyboard opens), scroll input into view
      if (vv.height < window.innerHeight * 0.85) {
        if (rafId != null) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(() => {
          rafId = null;
          el.scrollIntoView({ block: "end", behavior: "smooth" });
        });
      }
    };

    vv.addEventListener("resize", onResize);
    return () => {
      vv.removeEventListener("resize", onResize);
      if (rafId != null) cancelAnimationFrame(rafId);
    };
  }, []);

  /* ── Send message ── */
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text && pendingImages.length === 0) return;
    const attachedImages = pendingImages.length > 0 ? [...pendingImages] : undefined;
    setInput("");
    clearImages();
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    await sendMessage(courseId, text || "(image)", {
      activeTab: activeSection,
      images: attachedImages,
    });
  }, [activeSection, clearImages, courseId, input, pendingImages, sendMessage]);

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
  const handleInput = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
  }, []);

  const handleFilesUploaded = useCallback(() => {
    void fetchContentTree(courseId);
    void fetchIngestionJobs(courseId);
  }, [courseId, fetchContentTree, fetchIngestionJobs]);

  return (
    <div
      role="form"
      aria-label="Chat input"
      className={cn(
        "shrink-0 border-t border-border/60 bg-background px-3 py-2",
        isDragOver && "ring-2 ring-primary ring-inset bg-primary/5",
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Hidden image input */}
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        aria-label="Attach images"
        onChange={handleImageChange}
      />

      <ImagePreviewStrip
        images={pendingImages}
        onRemove={removeImage}
      />

      <div className="flex items-end gap-1.5 rounded-2xl border border-border/60 bg-muted/20 px-2 py-1.5">
        <AttachmentButtons
          courseId={courseId}
          disabled={isDisabled || isStreaming}
          pendingImageCount={pendingImages.length}
          onImageClick={handleImageClick}
          onFilesUploaded={handleFilesUploaded}
        />

        {/* Auto-growing textarea */}
        <span id="chat-input-hint" className="sr-only">
          Press Enter to send, Shift+Enter for new line
        </span>
        <textarea
          ref={textareaRef}
          data-testid="chat-input"
          data-chat-input
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          aria-label="Message input"
          aria-describedby="chat-input-hint"
          placeholder={
            isDisabled
              ? t("chat.disabledNeedLlm")
              : pendingImages.length > 0
                ? "Add a message about these images..."
                : "Ask anything..."
          }
          rows={1}
          disabled={isDisabled}
          className={cn(
            "flex-1 resize-none rounded-xl border-0 bg-transparent px-3 py-1.5 text-sm",
            "placeholder:text-muted-foreground",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "min-h-[32px] max-h-[96px]",
          )}
        />

        <SendButton
          isStreaming={isStreaming}
          canSend={canSend}
          onSend={() => void handleSend()}
          onStop={abortStream}
        />
      </div>

    </div>
  );
}
