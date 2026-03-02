"use client";

import { useEffect, useMemo, useState } from "react";
import {
  deriveQuestion,
  diagnoseWrongAnswer,
  getWrongAnswerReview,
  getWrongAnswerStats,
  listWrongAnswers,
  retryWrongAnswer,
  type DerivedQuestionResult,
  type WrongAnswer,
  type WrongAnswerStats,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface ReviewViewProps {
  courseId: string;
}

type FilterMode = "open" | "mastered" | "all";

export function ReviewView({ courseId }: ReviewViewProps) {
  const t = useT();
  const [items, setItems] = useState<WrongAnswer[]>([]);
  const [stats, setStats] = useState<WrongAnswerStats | null>(null);
  const [reviewSummary, setReviewSummary] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterMode>("open");
  const [retryAnswer, setRetryAnswer] = useState("");
  const [derivedQuestion, setDerivedQuestion] = useState<DerivedQuestionResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [wrongAnswersResult, statsResult, summaryResult] = await Promise.allSettled([
          listWrongAnswers(courseId),
          getWrongAnswerStats(courseId),
          getWrongAnswerReview(courseId),
        ]);

        if (cancelled) return;

        if (wrongAnswersResult.status === "fulfilled") {
          setItems(wrongAnswersResult.value);
          setSelectedId((current) => current ?? wrongAnswersResult.value[0]?.id ?? null);
        }
        if (statsResult.status === "fulfilled") {
          setStats(statsResult.value);
        }
        if (summaryResult.status === "fulfilled") {
          setReviewSummary(summaryResult.value.review);
        }
        if (
          wrongAnswersResult.status === "rejected" &&
          statsResult.status === "rejected" &&
          summaryResult.status === "rejected"
        ) {
          throw wrongAnswersResult.reason;
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load wrong-answer review");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const filteredItems = useMemo(() => {
    if (filter === "all") return items;
    if (filter === "mastered") return items.filter((item) => item.mastered);
    return items.filter((item) => !item.mastered);
  }, [filter, items]);

  const selected = filteredItems.find((item) => item.id === selectedId)
    ?? items.find((item) => item.id === selectedId)
    ?? filteredItems[0]
    ?? null;

  useEffect(() => {
    if (!selected) {
      setRetryAnswer("");
      setDerivedQuestion(null);
      return;
    }
    setSelectedId(selected.id);
    setRetryAnswer(selected.user_answer ?? "");
    setDerivedQuestion(null);
  }, [selected?.id]);

  const updateItem = (id: string, updater: (item: WrongAnswer) => WrongAnswer) => {
    setItems((current) => current.map((item) => (item.id === id ? updater(item) : item)));
  };

  const handleDiagnose = async () => {
    if (!selected) return;
    setWorking("diagnose");
    setError(null);
    setFeedback(null);
    try {
      const result = await diagnoseWrongAnswer(selected.id);
      updateItem(selected.id, (item) => ({
        ...item,
        diagnosis: result.diagnosis ?? item.diagnosis,
        error_detail: {
          ...(item.error_detail ?? {}),
          diagnosis: result.diagnosis ?? item.error_detail?.diagnosis,
          original_correct: result.original_correct ?? item.error_detail?.original_correct,
          clean_correct: result.clean_correct ?? item.error_detail?.clean_correct,
          diagnostic_problem_id: result.diagnostic_problem_id ?? item.error_detail?.diagnostic_problem_id,
        },
      }));
      setFeedback("Diagnosis updated.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to diagnose wrong answer");
    } finally {
      setWorking(null);
    }
  };

  const handleDerive = async () => {
    if (!selected) return;
    setWorking("derive");
    setError(null);
    setFeedback(null);
    try {
      setDerivedQuestion(await deriveQuestion(selected.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to derive diagnostic question");
    } finally {
      setWorking(null);
    }
  };

  const handleRetry = async () => {
    if (!selected || !retryAnswer.trim()) return;
    setWorking("retry");
    setError(null);
    setFeedback(null);
    try {
      const result = await retryWrongAnswer(selected.id, retryAnswer.trim());
      updateItem(selected.id, (item) => ({
        ...item,
        user_answer: retryAnswer.trim(),
        mastered: result.is_correct ? true : item.mastered,
        review_count: item.review_count + 1,
      }));
      if (result.is_correct) {
        setStats((current) => current ? {
          ...current,
          mastered: current.mastered + (selected.mastered ? 0 : 1),
          unmastered: Math.max(0, current.unmastered - (selected.mastered ? 0 : 1)),
        } : current);
      }
      setFeedback(
        result.is_correct
          ? "Marked as mastered."
          : result.explanation || "Still incorrect. Review the explanation and try again.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to retry answer");
    } finally {
      setWorking(null);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="h-4 w-36 rounded bg-muted animate-pulse" />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <h3 className="text-sm font-medium mb-1">{t("course.review")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          Wrong answers will show up here after you submit quiz attempts.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="space-y-4">
        {reviewSummary && (
          <section className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center justify-between gap-3 mb-2">
              <h3 className="text-sm font-medium">Review Summary</h3>
              <Badge variant="outline">{stats?.total ?? items.length} items</Badge>
            </div>
            <div className="whitespace-pre-wrap text-sm leading-6 text-foreground">
              {reviewSummary}
            </div>
          </section>
        )}

        {stats && (
          <section className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="text-xs text-muted-foreground">Total</div>
              <div className="mt-1 text-xl font-semibold">{stats.total}</div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="text-xs text-muted-foreground">Mastered</div>
              <div className="mt-1 text-xl font-semibold">{stats.mastered}</div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="text-xs text-muted-foreground">Needs review</div>
              <div className="mt-1 text-xl font-semibold">{stats.unmastered}</div>
            </div>
          </section>
        )}

        <div className="grid gap-4 xl:grid-cols-[320px,1fr]">
          <aside className="rounded-xl border border-border bg-card">
            <div className="border-b border-border px-4 py-3 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">{t("course.review")}</h3>
              <div className="flex gap-1">
                {(["open", "mastered", "all"] as FilterMode[]).map((mode) => (
                  <Button
                    key={mode}
                    type="button"
                    size="sm"
                    variant={filter === mode ? "default" : "outline"}
                    className="h-7 px-2 text-[11px]"
                    onClick={() => setFilter(mode)}
                  >
                    {mode}
                  </Button>
                ))}
              </div>
            </div>

            <div className="max-h-[560px] overflow-y-auto p-2 space-y-2">
              {filteredItems.map((item) => {
                const active = item.id === selected?.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedId(item.id)}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                      active
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/40"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="line-clamp-2 text-sm font-medium">
                        {item.question || "Untitled question"}
                      </span>
                      <Badge variant={item.mastered ? "secondary" : "outline"}>
                        {item.mastered ? "Mastered" : "Open"}
                      </Badge>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {item.error_category && (
                        <Badge variant="outline" className="text-[10px]">
                          {item.error_category}
                        </Badge>
                      )}
                      {item.diagnosis && (
                        <Badge variant="outline" className="text-[10px]">
                          {item.diagnosis}
                        </Badge>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          <section className="rounded-xl border border-border bg-card min-h-[560px]">
            {selected ? (
              <div className="p-4 space-y-4">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant={selected.mastered ? "secondary" : "outline"}>
                      {selected.mastered ? "Mastered" : "Needs review"}
                    </Badge>
                    {selected.question_type && (
                      <Badge variant="outline">{selected.question_type}</Badge>
                    )}
                  </div>
                  <h3 className="text-base font-semibold leading-6">{selected.question}</h3>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-border p-3">
                    <div className="text-xs text-muted-foreground mb-1">Your answer</div>
                    <div className="text-sm whitespace-pre-wrap">{selected.user_answer || "-"}</div>
                  </div>
                  <div className="rounded-lg border border-border p-3">
                    <div className="text-xs text-muted-foreground mb-1">Correct answer</div>
                    <div className="text-sm whitespace-pre-wrap">{selected.correct_answer || "-"}</div>
                  </div>
                </div>

                {selected.explanation && (
                  <div className="rounded-lg border border-border p-3">
                    <div className="text-xs text-muted-foreground mb-1">{t("quiz.explanation")}</div>
                    <div className="text-sm whitespace-pre-wrap leading-6">{selected.explanation}</div>
                  </div>
                )}

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-3">
                    <div className="rounded-lg border border-border p-3 space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <div className="text-sm font-medium">Retry answer</div>
                          <div className="text-xs text-muted-foreground">
                            Review count: {selected.review_count}
                          </div>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void handleRetry()}
                          disabled={working !== null || !retryAnswer.trim()}
                        >
                          {working === "retry" ? "Checking..." : "Submit retry"}
                        </Button>
                      </div>
                      <Textarea
                        value={retryAnswer}
                        onChange={(e) => setRetryAnswer(e.target.value)}
                        className="min-h-[120px] text-sm"
                      />
                    </div>

                    <div className="rounded-lg border border-border p-3 space-y-3">
                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void handleDiagnose()}
                          disabled={working !== null}
                        >
                          {working === "diagnose" ? "Diagnosing..." : "Diagnose"}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void handleDerive()}
                          disabled={working !== null}
                        >
                          {working === "derive" ? "Deriving..." : "Derive clean question"}
                        </Button>
                      </div>

                      <div className="text-sm space-y-1">
                        <div>
                          <span className="text-muted-foreground">Diagnosis:</span>{" "}
                          {selected.diagnosis || selected.error_detail?.diagnosis || "Not diagnosed yet"}
                        </div>
                        {selected.knowledge_points?.length ? (
                          <div className="flex flex-wrap gap-1 pt-1">
                            {selected.knowledge_points.map((point) => (
                              <Badge key={point} variant="outline" className="text-[10px]">
                                {point}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border border-border p-3">
                    <div className="text-sm font-medium mb-2">Derived question</div>
                    {derivedQuestion ? (
                      <div className="space-y-3 text-sm">
                        <div className="whitespace-pre-wrap leading-6">{derivedQuestion.question}</div>
                        {derivedQuestion.options && (
                          <div className="space-y-1">
                            {Object.entries(derivedQuestion.options).map(([key, value]) => (
                              <div key={key} className="rounded-md border border-border px-3 py-2">
                                <span className="font-medium mr-2">{key.toUpperCase()}.</span>
                                {value}
                              </div>
                            ))}
                          </div>
                        )}
                        {derivedQuestion.correct_answer && (
                          <div className="text-xs text-muted-foreground">
                            Correct answer: {derivedQuestion.correct_answer}
                          </div>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        Generate a simplified diagnostic question to compare concept understanding without traps.
                      </p>
                    )}
                  </div>
                </div>

                {(feedback || error) && (
                  <div className={`rounded-lg border px-3 py-2 text-sm ${
                    error
                      ? "border-destructive/30 bg-destructive/5 text-destructive"
                      : "border-border bg-muted/30 text-foreground"
                  }`}>
                    {error || feedback}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center p-8 text-center">
                <p className="text-xs text-muted-foreground">
                  Select a wrong answer to inspect it.
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
