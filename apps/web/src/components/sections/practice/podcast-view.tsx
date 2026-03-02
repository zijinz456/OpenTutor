"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { PodcastPlayer } from "@/components/audio/podcast-player";

interface PodcastViewProps {
  courseId: string;
}

type PodcastStyle = "review" | "deep_dive" | "exam_prep";

const STYLE_OPTIONS: { value: PodcastStyle; label: string }[] = [
  { value: "review", label: "Review" },
  { value: "deep_dive", label: "Deep Dive" },
  { value: "exam_prep", label: "Exam Prep" },
];

export function PodcastView({ courseId }: PodcastViewProps) {
  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState<PodcastStyle>("review");
  const [activePodcast, setActivePodcast] = useState<{
    topic: string;
    style: PodcastStyle;
  } | null>(null);

  const handleGenerate = () => {
    const t = topic.trim();
    if (!t) return;
    setActivePodcast({ topic: t, style });
  };

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
              if (e.key === "Enter") handleGenerate();
            }}
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
            >
              {opt.label}
            </Button>
          ))}
        </div>

        <Button
          size="sm"
          disabled={!topic.trim()}
          onClick={handleGenerate}
        >
          Generate Podcast
        </Button>
      </div>

      {activePodcast && (
        <PodcastPlayer
          key={`${activePodcast.topic}-${activePodcast.style}`}
          courseId={courseId}
          topic={activePodcast.topic}
          style={activePodcast.style}
        />
      )}
    </div>
  );
}
