"use client";

import { useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { buildAuthHeaders } from "@/lib/auth";
import { PodcastPlayer } from "@/components/audio/podcast-player";

interface PodcastViewProps {
  courseId: string;
}

type PodcastStyle = "review" | "deep_dive" | "exam_prep";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

const STYLE_OPTIONS: { value: PodcastStyle; label: string }[] = [
  { value: "review", label: "Review" },
  { value: "deep_dive", label: "Deep Dive" },
  { value: "exam_prep", label: "Exam Prep" },
];

export function PodcastView({ courseId }: PodcastViewProps) {
  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState<PodcastStyle>("review");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [podcast, setPodcast] = useState<{
    audioUrl: string;
    title: string;
    script?: { speaker: string; text: string }[];
  } | null>(null);

  // Track blob URL for cleanup
  const blobUrlRef = useRef<string | null>(null);

  const handleGenerate = useCallback(async () => {
    const t = topic.trim();
    if (!t) return;

    setGenerating(true);
    setError(null);

    // Revoke previous blob URL
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }

    try {
      const res = await fetch(`${API_BASE}/voice/podcast/${courseId}`, {
        method: "POST",
        headers: buildAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ topic: t, style }),
      });

      if (!res.ok) {
        throw new Error(`Generation failed (${res.status})`);
      }

      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);
      blobUrlRef.current = audioUrl;

      setPodcast({ audioUrl, title: t });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Podcast generation failed");
      setPodcast(null);
    } finally {
      setGenerating(false);
    }
  }, [courseId, topic, style]);

  return (
    <div className="flex-1 flex flex-col p-4 gap-4 overflow-y-auto">
      <div className="space-y-3">
        <div>
          <label htmlFor="podcast-topic" className="text-sm font-medium block mb-1">
            Topic
          </label>
          <input
            id="podcast-topic"
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Photosynthesis, Linear Algebra..."
            className="w-full rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleGenerate();
            }}
            disabled={generating}
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Style:</span>
          {STYLE_OPTIONS.map((opt) => (
            <Button
              key={opt.value}
              type="button"
              size="sm"
              variant={style === opt.value ? "secondary" : "ghost"}
              className="h-6 px-2 text-xs"
              onClick={() => setStyle(opt.value)}
              disabled={generating}
            >
              {opt.label}
            </Button>
          ))}
        </div>

        <Button
          size="sm"
          disabled={!topic.trim() || generating}
          onClick={() => void handleGenerate()}
        >
          {generating ? "Generating..." : "Generate Podcast"}
        </Button>

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
      </div>

      {podcast && (
        <PodcastPlayer
          key={podcast.audioUrl}
          audioUrl={podcast.audioUrl}
          title={podcast.title}
          script={podcast.script}
        />
      )}
    </div>
  );
}
