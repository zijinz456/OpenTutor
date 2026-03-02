"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Loader2,
  Podcast,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

type PodcastStyle = "review" | "deep_dive" | "exam_prep";

interface PodcastPlayerProps {
  courseId: string;
  topic: string;
  style?: PodcastStyle;
  className?: string;
}

/**
 * Podcast player component.
 *
 * Generates a study podcast from course materials via the backend,
 * then provides playback controls.
 */
export function PodcastPlayer({
  courseId,
  topic,
  style = "review",
  className,
}: PodcastPlayerProps) {
  const [state, setState] = useState<"idle" | "generating" | "ready" | "playing" | "paused" | "error">("idle");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [error, setError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    timerRef.current = setInterval(() => {
      if (audioRef.current) {
        setCurrentTime(audioRef.current.currentTime);
      }
    }, 250);
  }, [stopTimer]);

  /** Clean up previous audio element before creating a new one */
  const cleanupAudio = useCallback(() => {
    stopTimer();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute("src");
      audioRef.current.load();
      audioRef.current = null;
    }
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl);
      setAudioUrl(null);
    }
  }, [audioUrl, stopTimer]);

  /** Generate podcast from backend */
  const generate = useCallback(async () => {
    // Clean up any previous audio before generating new one
    cleanupAudio();

    setState("generating");
    setError(null);
    setCurrentTime(0);
    setDuration(0);

    try {
      const res = await fetch(`${API_BASE}/voice/podcast/${courseId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, style }),
      });

      if (!res.ok) {
        throw new Error(`Generation failed: ${res.statusText}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);

      const audio = new Audio(url);
      audioRef.current = audio;

      audio.addEventListener("loadedmetadata", () => {
        setDuration(audio.duration);
        setState("ready");
      });

      audio.addEventListener("ended", () => {
        setState("ready");
        setCurrentTime(0);
        stopTimer();
      });

      audio.addEventListener("error", () => {
        setState("error");
        setError("Failed to load audio");
      });
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Generation failed");
    }
  }, [courseId, topic, style, cleanupAudio, stopTimer]);

  const play = useCallback(() => {
    if (!audioRef.current) return;
    audioRef.current.playbackRate = playbackRate;
    audioRef.current.play().then(
      () => {
        setState("playing");
        startTimer();
      },
      (err) => {
        // Autoplay blocked or other playback error
        console.error("Playback failed:", err);
        setState("error");
        setError("Playback blocked — interact with the page and try again");
      },
    );
  }, [playbackRate, startTimer]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
    setState("paused");
    stopTimer();
  }, [stopTimer]);

  const seek = useCallback((seconds: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, Math.min(seconds, duration));
    setCurrentTime(audioRef.current.currentTime);
  }, [duration]);

  const skip = useCallback((delta: number) => {
    if (!audioRef.current) return;
    seek(audioRef.current.currentTime + delta);
  }, [seek]);

  const cycleSpeed = useCallback(() => {
    const speeds = [0.75, 1.0, 1.25, 1.5, 2.0];
    const idx = speeds.indexOf(playbackRate);
    const next = speeds[(idx + 1) % speeds.length];
    setPlaybackRate(next);
    if (audioRef.current) {
      audioRef.current.playbackRate = next;
    }
  }, [playbackRate]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.removeAttribute("src");
        audioRef.current.load();
      }
    };
  }, []);

  // Revoke object URL on unmount or URL change
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  if (state === "idle") {
    return (
      <div className={cn("flex items-center gap-3 rounded-lg border p-3", className)}>
        <Podcast className="size-5 text-muted-foreground" />
        <div className="flex-1">
          <p className="text-sm font-medium">Study Podcast</p>
          <p className="text-xs text-muted-foreground">{topic}</p>
        </div>
        <Button size="sm" onClick={() => void generate()}>
          Generate
        </Button>
      </div>
    );
  }

  if (state === "generating") {
    return (
      <div className={cn("flex items-center gap-3 rounded-lg border p-3", className)}>
        <Loader2 className="size-5 animate-spin text-primary" />
        <div className="flex-1">
          <p className="text-sm font-medium">Generating podcast...</p>
          <p className="text-xs text-muted-foreground">Creating dialogue and synthesizing audio for: {topic}</p>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className={cn("flex items-center gap-3 rounded-lg border border-destructive/30 p-3", className)}>
        <Podcast className="size-5 text-destructive" />
        <div className="flex-1">
          <p className="text-sm font-medium text-destructive">Generation failed</p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => void generate()}>
          Retry
        </Button>
      </div>
    );
  }

  // Ready / Playing / Paused
  return (
    <div className={cn("rounded-lg border p-3 space-y-2", className)}>
      <div className="flex items-center gap-2">
        <Podcast className="size-4 text-primary" />
        <span className="text-sm font-medium flex-1">{topic}</span>
        <button
          type="button"
          onClick={cycleSpeed}
          className="text-xs px-1.5 py-0.5 rounded bg-muted hover:bg-muted/80 font-mono"
          title="Change playback speed"
        >
          {playbackRate}x
        </button>
      </div>

      {/* Progress bar */}
      <div
        className="relative h-1.5 rounded-full bg-muted cursor-pointer"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const pct = (e.clientX - rect.left) / rect.width;
          seek(pct * duration);
        }}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all"
          style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
        />
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground font-mono">
          {formatTime(currentTime)}
        </span>

        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            onClick={() => skip(-15)}
            title="Back 15s"
          >
            <SkipBack className="size-3.5" />
          </Button>

          <Button
            type="button"
            variant="default"
            size="icon-xs"
            onClick={state === "playing" ? pause : play}
            title={state === "playing" ? "Pause" : "Play"}
          >
            {state === "playing" ? (
              <Pause className="size-3.5" />
            ) : (
              <Play className="size-3.5" />
            )}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            onClick={() => skip(15)}
            title="Forward 15s"
          >
            <SkipForward className="size-3.5" />
          </Button>
        </div>

        <span className="text-[11px] text-muted-foreground font-mono">
          {formatTime(duration)}
        </span>
      </div>
    </div>
  );
}
