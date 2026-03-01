"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
import { listProblems } from "@/lib/api";

/**
 * Shows a brief banner when AI has auto-generated starter quiz/flashcards
 * after content ingestion. Disappears after the user dismisses it or after
 * 30 seconds. Only shown once per course (tracked via localStorage).
 */
export function AutoGenBanner({
  courseId,
  onQuizReady,
}: {
  courseId: string;
  onQuizReady?: () => void;
}) {
  const [visible, setVisible] = useState(false);
  const [quizCount, setQuizCount] = useState(0);
  const [polling, setPolling] = useState(true);
  const [dismissed, setDismissed] = useState(false);

  const storageKey = `autogen_shown_${courseId}`;

  // Check if already dismissed for this course
  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem(storageKey)) {
      setPolling(false);
    }
  }, [storageKey]);

  // Poll for auto-generated content (every 5s, up to 60s)
  useEffect(() => {
    if (!polling || dismissed) return;

    let attempts = 0;
    const maxAttempts = 12; // 60 seconds total

    const check = async () => {
      try {
        const problems = await listProblems(courseId);
        if (problems.length > 0 && quizCount === 0) {
          setQuizCount(problems.length);
          setVisible(true);
          setPolling(false);
          localStorage.setItem(storageKey, "1");
        }
      } catch {
        // ignore
      }
      attempts++;
      if (attempts >= maxAttempts) {
        setPolling(false);
      }
    };

    // Initial check
    check();
    const interval = setInterval(check, 5000);
    return () => clearInterval(interval);
  }, [courseId, polling, dismissed, quizCount, storageKey]);

  // Auto-hide after 15 seconds
  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(() => setVisible(false), 15000);
    return () => clearTimeout(timer);
  }, [visible]);

  const handleDismiss = useCallback(() => {
    setVisible(false);
    setDismissed(true);
  }, []);

  if (!visible) return null;

  return (
    <div className="mx-4 mt-2 mb-1 rounded-lg border border-indigo-200 bg-indigo-50 dark:bg-indigo-950/30 dark:border-indigo-800 px-4 py-2.5 flex items-center gap-3 animate-in slide-in-from-top-2 duration-300">
      <Sparkles className="h-4 w-4 text-indigo-500 shrink-0" />
      <div className="flex-1 text-sm">
        <span className="font-medium text-indigo-700 dark:text-indigo-300">AI prepared your materials</span>
        <span className="text-indigo-600/70 dark:text-indigo-400/70 ml-1.5">
          &mdash; {quizCount} quiz questions ready
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {quizCount > 0 && (
          <button
            onClick={() => { onQuizReady?.(); handleDismiss(); }}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 dark:text-indigo-400"
          >
            Try Quiz
          </button>
        )}
        <button onClick={handleDismiss} className="text-indigo-400 hover:text-indigo-600">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
