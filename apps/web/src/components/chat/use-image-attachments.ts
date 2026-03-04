"use client";

import {
  useRef,
  useState,
  useCallback,
  type ChangeEvent,
  type DragEvent,
  type ClipboardEvent,
} from "react";
import type { ImageAttachment } from "@/lib/api";
import { toast } from "sonner";
import {
  MAX_IMAGES,
  MAX_IMAGE_SIZE,
  fileToImageAttachment,
} from "@/components/chat/chat-input-utils";

/**
 * Manages pending image attachments: add via file picker, paste, or drag-and-drop.
 * Returns all state and handlers needed by ChatInput for image operations.
 */
export function useImageAttachments() {
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [pendingImages, setPendingImages] = useState<ImageAttachment[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);

  const addImages = useCallback(
    async (files: File[]) => {
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
    },
    [pendingImages.length],
  );

  const removeImage = useCallback((index: number) => {
    setPendingImages((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearImages = useCallback(() => {
    setPendingImages([]);
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

  return {
    imageInputRef,
    pendingImages,
    isDragOver,
    removeImage,
    clearImages,
    handleImageClick,
    handleImageChange,
    handlePaste,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  };
}
