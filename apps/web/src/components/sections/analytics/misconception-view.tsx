"use client";

import { useEffect, useState } from "react";
import { getMisconceptionDashboard, type MisconceptionDashboard, type MisconceptionItem } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

interface MisconceptionViewProps {
  courseId: string;
}

const DIAGNOSIS_LABELS: Record<string, string> = {
  fundamental_gap: "Fundamental Gap",
  transfer_gap: "Transfer Gap",
  trap_vulnerability: "Trap Vulnerability",
  carelessness: "Carelessness",
  mastered: "Mastered",
};

const MISCONCEPTION_TYPE_LABELS: Record<string, string> = {
  surface_memorization: "Surface Memorization",
  confused_similar: "Confused Similar Concepts",
  missing_prerequisite: "Missing Prerequisite",
  procedural_only: "Procedural Only",
  partial_understanding: "Partial Understanding",
};

const DIAGNOSIS_COLORS: Record<string, string> = {
  fundamental_gap: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  transfer_gap: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  trap_vulnerability: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
  carelessness: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
};

function PriorityBar({ score }: { score: number }) {
  const maxScore = 5;
  const pct = Math.min(score / maxScore, 1) * 100;
  const color = pct > 66 ? "bg-red-500" : pct > 33 ? "bg-amber-500" : "bg-zinc-400";
  return (
    <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function MisconceptionCard({ item, rank }: { item: MisconceptionItem; rank: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      role="button"
      aria-expanded={expanded}
      tabIndex={0}
      className="rounded-2xl card-shadow bg-card p-3.5 space-y-2 cursor-pointer hover:bg-accent/50 transition-colors"
      onClick={() => setExpanded(!expanded)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(!expanded); } }}
      data-testid={`misconception-card-${rank}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs text-muted-foreground font-mono w-5 shrink-0">
            #{rank}
          </span>
          <span className="text-sm font-medium truncate">{item.concept}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <PriorityBar score={item.priority_score} />
          <span className="text-xs tabular-nums text-muted-foreground">
            {item.active_errors} active
          </span>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {item.dominant_diagnosis ? (
          <Badge
            variant="outline"
            className={`text-[10px] ${DIAGNOSIS_COLORS[item.dominant_diagnosis] ?? "bg-muted text-muted-foreground"}`}
          >
            {DIAGNOSIS_LABELS[item.dominant_diagnosis] ?? item.dominant_diagnosis}
          </Badge>
        ) : null}
        {item.dominant_misconception_type ? (
          <Badge variant="outline" className="text-[10px] bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300">
            {MISCONCEPTION_TYPE_LABELS[item.dominant_misconception_type] ?? item.dominant_misconception_type}
          </Badge>
        ) : null}
        {item.resolution_rate > 0 ? (
          <Badge variant="outline" className="text-[10px] bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
            {item.resolution_rate}% resolved
          </Badge>
        ) : null}
      </div>

      {expanded && item.sample_questions.length > 0 ? (
        <div className="mt-2 space-y-2 border-t border-border/60 pt-2">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Sample errors
          </span>
          {item.sample_questions.map((q, i) => (
            <div key={i} className="text-xs space-y-0.5 pl-2 border-l-2 border-muted">
              <p className="text-foreground line-clamp-2">{q.question}</p>
              <p className="text-red-600 dark:text-red-400">
                Your answer: {q.user_answer || "—"}
              </p>
              <p className="text-green-600 dark:text-green-400">
                Correct: {q.correct_answer || "—"}
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function MisconceptionView({ courseId }: MisconceptionViewProps) {
  const [data, setData] = useState<MisconceptionDashboard | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMisconceptionDashboard(courseId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (error) {
    return (
      <div
        className="flex-1 flex items-center justify-center p-8 text-xs text-muted-foreground"
        data-testid="misconception-panel"
      >
        Failed to load misconception data.
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex flex-col gap-3 p-4" data-testid="misconception-panel">
        <div className="h-4 w-48 bg-muted animate-pulse rounded" />
        <div className="h-16 w-full bg-muted animate-pulse rounded" />
        <div className="h-16 w-full bg-muted animate-pulse rounded" />
      </div>
    );
  }

  const { misconceptions, summary } = data;

  if (misconceptions.length === 0) {
    return (
      <div
        className="flex-1 flex flex-col items-center justify-center p-8 text-center gap-2"
        data-testid="misconception-panel"
      >
        <span className="text-2xl">&#10003;</span>
        <p className="text-sm text-muted-foreground">No active misconceptions detected.</p>
        <p className="text-xs text-muted-foreground">
          Keep practicing — the tutor will probe your understanding as you learn.
        </p>
      </div>
    );
  }

  const diagEntries = Object.entries(summary.diagnosis_breakdown).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <div
      role="region"
      aria-label="Misconception analysis"
      className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto"
      data-testid="misconception-panel"
    >
      <div>
        <h3 className="text-sm font-medium">
          Things You Think You Know
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5">
          Concepts where errors suggest hidden misunderstanding, ranked by priority.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-2xl card-shadow bg-card p-3 flex flex-col gap-0.5">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Active</span>
          <span className="text-xl font-semibold tabular-nums">{summary.total_active_errors}</span>
        </div>
        <div className="rounded-2xl card-shadow bg-card p-3 flex flex-col gap-0.5">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Resolved</span>
          <span className="text-xl font-semibold tabular-nums">{summary.total_resolved}</span>
        </div>
        <div className="rounded-2xl card-shadow bg-card p-3 flex flex-col gap-0.5">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Rate</span>
          <span className="text-xl font-semibold tabular-nums">{summary.resolution_rate}%</span>
        </div>
      </div>

      {/* Diagnosis breakdown badges */}
      {diagEntries.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {diagEntries.map(([diag, count]) => (
            <Badge
              key={diag}
              variant="outline"
              className={`text-[10px] ${DIAGNOSIS_COLORS[diag] ?? "bg-muted text-muted-foreground"}`}
            >
              {DIAGNOSIS_LABELS[diag] ?? diag} ({count})
            </Badge>
          ))}
        </div>
      ) : null}

      {/* Misconception cards */}
      <div className="space-y-2">
        {misconceptions.map((item, i) => (
          <MisconceptionCard key={item.concept} item={item} rank={i + 1} />
        ))}
      </div>
    </div>
  );
}
