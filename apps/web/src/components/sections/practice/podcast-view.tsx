"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { buildAuthHeaders } from "@/lib/auth";
import { PodcastPlayer } from "@/components/audio/podcast-player";

interface PodcastViewProps {
  courseId: string;
}

type PodcastStyle = "review" | "deep_dive" | "exam_prep";
type PodcastLine = { role?: string; speaker?: string; text: string };

interface PodcastHistoryItem {
  id: string;
  title: string;
  topic: string;
  style: PodcastStyle;
  dialogue: PodcastLine[];
  created_at: string | null;
}

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
  const [history, setHistory] = useState<PodcastHistoryItem[]>([]);

  // Track blob URL for cleanup
  const blobUrlRef = useRef<string | null>(null);

  const normalizeScript = useCallback(
    (dialogue?: PodcastLine[]) =>
      dialogue?.map((line) => ({
        speaker: line.speaker ?? line.role?.toUpperCase() ?? "HOST",
        text: line.text,
      })),
    [],
  );

  const loadHistory = useCallback(async (): Promise<PodcastHistoryItem[]> => {
    try {
      const res = await fetch(
        `${API_BASE}/podcast/list?course_id=${encodeURIComponent(courseId)}`,
        { headers: buildAuthHeaders() },
      );
      if (!res.ok) {
        throw new Error(`Failed to load podcast history (${res.status})`);
      }
      const data = (await res.json()) as PodcastHistoryItem[];
      setHistory(data);
      return data;
    } catch {
      setHistory([]);
      return [];
    }
  }, [courseId]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => () => {
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
  }, []);

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
      const res = await fetch(`${API_BASE}/podcast/generate`, {
        method: "POST",
        headers: buildAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ course_id: courseId, topic: t, style }),
      });

      if (!res.ok) {
        throw new Error(`Generation failed (${res.status})`);
      }

      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);
      blobUrlRef.current = audioUrl;
      const latestHistory = await loadHistory();
      const matchedItem = latestHistory.find(
        (item) => item.topic === t && item.style === style,
      );

      setPodcast({
        audioUrl,
        title: t,
        script: normalizeScript(matchedItem?.dialogue),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Podcast generation failed");
      setPodcast(null);
    } finally {
      setGenerating(false);
    }
  }, [courseId, loadHistory, normalizeScript, style, topic]);

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

      {history.length > 0 && (
        <div className="rounded-lg border border-border p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium text-foreground">Recent podcasts</h3>
            <span className="text-xs text-muted-foreground">{history.length} saved</span>
          </div>
          <div className="space-y-2">
            {history.slice(0, 5).map((item) => (
              <button
                key={item.id}
                type="button"
                className="w-full rounded-md border border-border px-3 py-2 text-left hover:bg-accent"
                onClick={() => {
                  setTopic(item.topic);
                  setStyle(item.style);
                  setPodcast((current) =>
                    current
                      ? { ...current, title: item.topic, script: normalizeScript(item.dialogue) }
                      : null,
                  );
                }}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-foreground">{item.topic}</span>
                  <span className="text-xs uppercase text-muted-foreground">{item.style}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.created_at ? new Date(item.created_at).toLocaleString() : "Saved"}
                </p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
