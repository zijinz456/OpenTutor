"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle2, ChevronLeft, ChevronRight } from "lucide-react";
import {
  getReviewSession,
  type ReviewItem,
  type ReviewSession,
} from "@/lib/api/progress";

type Rating = "again" | "hard" | "good" | "easy";

export default function ReviewPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params.id as string;

  const [sessionByCourse, setSessionByCourse] = useState<Record<string, ReviewSession>>({});
  const [errorByCourse, setErrorByCourse] = useState<Record<string, string>>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [ratings, setRatings] = useState<Map<string, Rating>>(new Map());

  const session = sessionByCourse[courseId] ?? null;
  const error = errorByCourse[courseId] ?? null;
  const loading = !session && !error;

  useEffect(() => {
    if (sessionByCourse[courseId] || errorByCourse[courseId]) return;
    let cancelled = false;
    getReviewSession(courseId, 20)
      .then((data) => {
        if (cancelled) return;
        setSessionByCourse((prev) => ({ ...prev, [courseId]: data }));
        if (data.items.length === 0) {
          setErrorByCourse((prev) => ({ ...prev, [courseId]: "No items to review right now." }));
        }
      })
      .catch(() => {
        if (cancelled) return;
        setErrorByCourse((prev) => ({ ...prev, [courseId]: "Failed to load review session." }));
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, errorByCourse, sessionByCourse]);

  const items = session?.items ?? [];
  const current = items[currentIndex] as ReviewItem | undefined;
  const total = items.length;
  const reviewed = ratings.size;
  const allDone = reviewed === total && total > 0;

  const handleRate = useCallback(
    (rating: Rating) => {
      if (!current) return;
      setRatings((prev) => new Map(prev).set(current.concept_id, rating));
      setRevealed(false);
      if (currentIndex < total - 1) {
        setCurrentIndex((i) => i + 1);
      }
    },
    [current, currentIndex, total],
  );

  const goBack = () => router.push(`/course/${courseId}`);

  const urgencyColor = (urgency: string) => {
    switch (urgency) {
      case "overdue":
        return "text-destructive";
      case "urgent":
        return "text-warning-foreground bg-warning-muted";
      case "warning":
        return "text-warning-foreground bg-warning-muted/60";
      default:
        return "text-muted-foreground bg-muted";
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground animate-pulse">Loading review session...</p>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground">{error || "No review data available."}</p>
        <button
          type="button"
          onClick={goBack}
          className="text-sm text-brand hover:underline"
        >
          Back to course
        </button>
      </div>
    );
  }

  if (allDone) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-6">
        <CheckCircle2 className="size-16 text-success" />
        <h1 className="text-2xl font-bold text-foreground">Review Complete</h1>
        <p className="text-muted-foreground text-center max-w-md">
          You reviewed {total} concept{total !== 1 ? "s" : ""}. Keep it up!
        </p>
        <button
          type="button"
          onClick={goBack}
          className="px-6 py-2.5 rounded-lg bg-brand text-brand-foreground font-medium hover:opacity-90 transition-opacity"
        >
          Back to course
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-4 py-3 flex items-center gap-4">
        <button type="button" onClick={goBack} className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft className="size-5" />
        </button>
        <h1 className="text-sm font-semibold text-foreground">Review Session</h1>
        <div className="flex-1" />
        <span className="text-xs text-muted-foreground">
          {reviewed} / {total} reviewed
        </span>
      </header>

      {/* Progress bar */}
      <div className="h-1 bg-muted">
        <div
          className="h-full bg-brand transition-all duration-300"
          style={{ width: `${total > 0 ? (reviewed / total) * 100 : 0}%` }}
        />
      </div>

      {/* Card area */}
      <main className="flex-1 flex flex-col items-center justify-center p-6">
        {current && (
          <div className="w-full max-w-lg space-y-6">
            {/* Navigation */}
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => {
                  setRevealed(false);
                  setCurrentIndex((i) => Math.max(0, i - 1));
                }}
                disabled={currentIndex === 0}
                className="p-2 rounded-lg hover:bg-muted disabled:opacity-30 transition-colors"
              >
                <ChevronLeft className="size-5" />
              </button>
              <span className="text-sm text-muted-foreground">
                {currentIndex + 1} of {total}
              </span>
              <button
                type="button"
                onClick={() => {
                  setRevealed(false);
                  setCurrentIndex((i) => Math.min(total - 1, i + 1));
                }}
                disabled={currentIndex === total - 1}
                className="p-2 rounded-lg hover:bg-muted disabled:opacity-30 transition-colors"
              >
                <ChevronRight className="size-5" />
              </button>
            </div>

            {/* Card */}
            <div className="rounded-2xl border border-border bg-card p-8 text-center space-y-4 min-h-[240px] flex flex-col items-center justify-center">
              <h2 className="text-xl font-semibold text-foreground">
                {current.concept_label}
              </h2>

              <div className="flex items-center gap-2 flex-wrap justify-center">
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${urgencyColor(current.urgency)}`}>
                  {current.urgency}
                </span>
                <span className="text-xs text-muted-foreground">
                  Mastery: {Math.round(current.mastery * 100)}%
                </span>
                <span className="text-xs text-muted-foreground">
                  Stability: {current.stability_days.toFixed(1)}d
                </span>
              </div>

              {!revealed ? (
                <button
                  type="button"
                  onClick={() => setRevealed(true)}
                  className="mt-4 px-5 py-2 rounded-lg bg-brand text-brand-foreground text-sm font-medium hover:opacity-90 transition-opacity"
                >
                  Show Details
                </button>
              ) : (
                <div className="mt-4 space-y-2 text-sm text-muted-foreground">
                  <p>Retrievability: {Math.round(current.retrievability * 100)}%</p>
                  {current.cluster && <p>Cluster: {current.cluster}</p>}
                  {current.last_reviewed && (
                    <p>Last reviewed: {new Date(current.last_reviewed).toLocaleDateString()}</p>
                  )}
                </div>
              )}
            </div>

            {/* Rating buttons */}
            {revealed && (
              <div className="grid grid-cols-4 gap-2">
                {(
                  [
                    { key: "again", label: "Again", color: "bg-destructive/10 text-destructive hover:bg-destructive/20" },
                    { key: "hard", label: "Hard", color: "bg-warning-muted text-warning-foreground hover:bg-warning-muted/80" },
                    { key: "good", label: "Good", color: "bg-success-muted text-success hover:bg-success-muted/80" },
                    { key: "easy", label: "Easy", color: "bg-brand-muted text-brand hover:bg-brand-muted/80" },
                  ] as const
                ).map(({ key, label, color }) => (
                  <button
                    type="button"
                    key={key}
                    onClick={() => handleRate(key)}
                    className={`py-2.5 rounded-lg text-sm font-medium transition-colors ${color}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}

            {/* Already rated indicator */}
            {ratings.has(current.concept_id) && (
              <p className="text-xs text-center text-success">
                Rated: {ratings.get(current.concept_id)}
              </p>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
