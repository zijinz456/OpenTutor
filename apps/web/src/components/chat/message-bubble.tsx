"use client";

import Image from "next/image";
import { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/store/chat";
import { ActionCard } from "@/components/chat/action-card";
import { Play, Pause, Volume2 } from "lucide-react";

interface MessageBubbleProps {
  message: ChatMessage;
}

/**
 * Single message bubble.
 *
 * - User messages: right-aligned, chat-user colours.
 * - Assistant messages: left-aligned, chat-assistant colours with
 *   whitespace-pre-wrap (markdown renderer to be added later).
 * - Shows ActionCard components when metadata.actions is present.
 * - Displays attached images for user messages.
 * - Shows audio playback controls for voice responses.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const actions = message.metadata?.actions;
  const images = message.images;
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  return (
    <>
      <div
        className={cn("flex mb-2", isUser ? "justify-end" : "justify-start")}
        data-testid={isUser ? "chat-message-user" : "chat-message-assistant"}
        data-role={message.role}
      >
        <div
          className={cn(
            "max-w-[85%] rounded-lg px-3 py-2 text-sm",
            isUser
              ? "bg-[var(--chat-user-bg,hsl(var(--primary)))] text-[var(--chat-user-fg,hsl(var(--primary-foreground)))]"
              : "bg-[var(--chat-assistant-bg,hsl(var(--muted)))] text-[var(--chat-assistant-fg,hsl(var(--foreground)))]",
          )}
        >
          {/* Attached images (user messages) */}
          {isUser && images && images.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {images.map((img, i) => (
                <button
                  key={`${img.filename ?? "img"}-${i}`}
                  type="button"
                  className="rounded-md overflow-hidden border border-white/20 hover:opacity-80 transition-opacity"
                  onClick={() =>
                    setExpandedImage(`data:${img.media_type};base64,${img.data}`)
                  }
                >
                  <Image
                    src={`data:${img.media_type};base64,${img.data}`}
                    alt={img.filename ?? `Image ${i + 1}`}
                    width={80}
                    height={80}
                    unoptimized
                    className="h-20 w-20 object-cover"
                  />
                </button>
              ))}
            </div>
          )}

          {/* Message content */}
          {message.content && message.content !== "(image)" ? (
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          ) : !images?.length ? (
            <span className="text-xs italic opacity-60">...</span>
          ) : null}

          {/* Audio playback for voice responses */}
          {!isUser && message.audioUrl && (
            <AudioPlayer src={message.audioUrl} />
          )}

          {/* Action cards from metadata */}
          {!isUser && actions && actions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {actions.map((action, i) => (
                <ActionCard
                  key={`${action.action}-${i}`}
                  action={{
                    type: action.action,
                    label: action.value ?? action.action,
                    payload: action.extra ? { extra: action.extra } : undefined,
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Expanded image overlay */}
      {expandedImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 cursor-pointer"
          onClick={() => setExpandedImage(null)}
          role="dialog"
          aria-label="Expanded image"
        >
          <Image
            src={expandedImage}
            alt="Expanded view"
            width={1440}
            height={1080}
            unoptimized
            className="max-h-[85vh] max-w-[90vw] rounded-lg object-contain"
          />
        </div>
      )}
    </>
  );
}

/** Inline audio player for TTS voice responses. */
function AudioPlayer({ src }: { src: string }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const a = new Audio(src);
    const onEnded = () => setIsPlaying(false);
    a.addEventListener("ended", onEnded);
    audioRef.current = a;
    return () => {
      a.pause();
      a.removeEventListener("ended", onEnded);
      a.removeAttribute("src");
      audioRef.current = null;
    };
  }, [src]);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      audio.play().then(
        () => setIsPlaying(true),
        () => setIsPlaying(false), // Autoplay blocked or load error
      );
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className="mt-1.5 flex items-center gap-1.5 rounded-md bg-black/10 px-2 py-1 text-xs hover:bg-black/15 transition-colors"
      aria-label={isPlaying ? "Pause audio" : "Play audio"}
    >
      {isPlaying ? <Pause className="size-3" /> : <Play className="size-3" />}
      <Volume2 className="size-3 opacity-60" />
      <span>Voice response</span>
    </button>
  );
}
