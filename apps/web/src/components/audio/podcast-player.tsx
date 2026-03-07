"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Podcast,
} from "lucide-react";

interface PodcastPlayerProps {
  audioUrl: string;
  title: string;
  script?: { speaker: string; text: string }[];
  className?: string;
}

const PLAYBACK_SPEEDS = [0.75, 1, 1.25, 1.5, 2] as const;

/**
 * Podcast player component.
 *
 * Renders an audio player with playback controls, a progress bar,
 * speed selector, and optional dialogue script display.
 */
export function PodcastPlayer({
  audioUrl,
  title,
  script,
  className,
}: PodcastPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Initialize audio element
  useEffect(() => {
    const audio = new Audio(audioUrl);
    audioRef.current = audio;

    const onLoadedMetadata = () => setDuration(audio.duration);
    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);

    audio.addEventListener("loadedmetadata", onLoadedMetadata);
    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);

    return () => {
      audio.removeEventListener("loadedmetadata", onLoadedMetadata);
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      audioRef.current = null;
    };
  }, [audioUrl]);

  const play = useCallback(() => {
    if (!audioRef.current) return;
    audioRef.current.playbackRate = playbackRate;
    audioRef.current.play().then(
      () => {},
      (err) => {
        console.error("Playback failed:", err);
      },
    );
  }, [playbackRate]);

  const pause = useCallback(() => {
    audioRef.current?.pause();
  }, []);

  const seek = useCallback(
    (seconds: number) => {
      if (!audioRef.current) return;
      audioRef.current.currentTime = Math.max(0, Math.min(seconds, duration));
      setCurrentTime(audioRef.current.currentTime);
    },
    [duration],
  );

  const skip = useCallback(
    (delta: number) => {
      if (!audioRef.current) return;
      seek(audioRef.current.currentTime + delta);
    },
    [seek],
  );

  const cycleSpeed = useCallback(() => {
    const idx = PLAYBACK_SPEEDS.indexOf(playbackRate as (typeof PLAYBACK_SPEEDS)[number]);
    const next = PLAYBACK_SPEEDS[(idx + 1) % PLAYBACK_SPEEDS.length];
    setPlaybackRate(next);
    if (audioRef.current) {
      audioRef.current.playbackRate = next;
    }
  }, [playbackRate]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  const progressPct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <Card className={cn("w-full rounded-2xl card-shadow", className)}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Podcast className="size-5 text-primary" />
          {title}
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Progress bar */}
        <div
          className="relative h-2 cursor-pointer rounded-full bg-muted"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;
            seek(pct * duration);
          }}
        >
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-primary transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {/* Controls */}
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs text-muted-foreground">
            {formatTime(currentTime)}
          </span>

          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => skip(-15)}
              title="Back 15s"
            >
              <SkipBack className="size-4" />
            </Button>

            <Button
              type="button"
              variant="default"
              size="icon"
              onClick={isPlaying ? pause : play}
              title={isPlaying ? "Pause" : "Play"}
            >
              {isPlaying ? (
                <Pause className="size-4" />
              ) : (
                <Play className="size-4" />
              )}
            </Button>

            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => skip(15)}
              title="Forward 15s"
            >
              <SkipForward className="size-4" />
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={cycleSpeed}
              className="rounded-full bg-muted px-2 py-0.5 font-mono text-xs hover:bg-muted/80"
              title="Change playback speed"
            >
              {playbackRate}x
            </button>
            <span className="font-mono text-xs text-muted-foreground">
              {formatTime(duration)}
            </span>
          </div>
        </div>

        {/* Dialogue script */}
        {script && script.length > 0 && (
          <div className="mt-4 max-h-64 space-y-3 overflow-y-auto scrollbar-thin rounded-xl bg-muted/30 p-3.5">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Transcript
            </p>
            {script.map((line, i) => (
              <div key={i} className="flex gap-2 text-sm">
                <span className="shrink-0 font-semibold text-primary">
                  {line.speaker}:
                </span>
                <span className="text-foreground">{line.text}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
