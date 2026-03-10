"use client";

import Image from "next/image";
import type { ImageAttachment } from "@/lib/api";
import { X } from "lucide-react";

interface ImagePreviewStripProps {
  images: ImageAttachment[];
  onRemove: (index: number) => void;
}

/**
 * Horizontal strip of thumbnail previews for pending image attachments.
 * Each thumbnail has a hover-revealed remove button.
 */
export function ImagePreviewStrip({ images, onRemove }: ImagePreviewStripProps) {
  if (images.length === 0) return null;

  return (
    <div role="list" aria-label="Attached images" className="mb-2 flex gap-2 overflow-x-auto scrollbar-thin pb-1">
      {images.map((img, i) => (
        <div
          key={`${img.filename ?? "img"}-${i}`}
          role="listitem"
          className="relative shrink-0 group"
        >
          <Image
            src={`data:${img.media_type};base64,${img.data}`}
            alt={img.filename ?? `Image ${i + 1}`}
            width={64}
            height={64}
            unoptimized
            className="h-16 w-16 rounded-xl object-cover border border-border/60"
          />
          <button
            type="button"
            onClick={() => onRemove(i)}
            className="absolute -top-1.5 -right-1.5 rounded-full bg-destructive text-destructive-foreground p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
            aria-label="Remove image"
          >
            <X className="size-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
