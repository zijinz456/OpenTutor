"use client";

import { useEffect, useMemo, useState } from "react";
import { listStudyGoals, type StudyGoal } from "@/lib/api";

interface TimelineViewProps {
  courseId: string;
}

const URGENCY_COLORS = {
  overdue: "bg-destructive text-destructive-foreground",
  soon: "bg-warning text-warning-foreground",
  normal: "bg-brand text-brand-foreground",
  future: "bg-muted text-muted-foreground",
};

function getUrgency(daysLeft: number): keyof typeof URGENCY_COLORS {
  if (daysLeft < 0) return "overdue";
  if (daysLeft <= 7) return "soon";
  if (daysLeft <= 30) return "normal";
  return "future";
}

function formatDaysLeft(daysLeft: number): string {
  if (daysLeft < 0) return `${Math.abs(daysLeft)}天前过期`;
  if (daysLeft === 0) return "今天";
  if (daysLeft === 1) return "明天";
  return `${daysLeft}天后`;
}

export function TimelineView({ courseId }: TimelineViewProps) {
  const [goals, setGoals] = useState<StudyGoal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    listStudyGoals(courseId)
      .then((g) => setGoals(g))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [courseId]);

  const today = useMemo(() => new Date(), []);

  // Sort goals with deadlines, then without
  const sorted = useMemo(() => {
    const withDate = goals
      .filter((g) => g.target_date)
      .sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime());
    const withoutDate = goals.filter((g) => !g.target_date);
    return [...withDate, ...withoutDate];
  }, [goals]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        加载中…
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 gap-2 text-center p-6">
        <p className="text-sm text-muted-foreground">暂无学习目标</p>
        <p className="text-xs text-muted-foreground">在计划视图中添加目标，时间线将显示在这里</p>
      </div>
    );
  }

  // Build time extent for the timeline bar (from earliest to latest + 7d buffer)
  const goalsWithDate = sorted.filter((g) => g.target_date);
  const earliestMs = goalsWithDate.length > 0
    ? Math.min(today.getTime(), new Date(goalsWithDate[0].target_date!).getTime())
    : today.getTime();
  const latestMs = goalsWithDate.length > 0
    ? new Date(goalsWithDate[goalsWithDate.length - 1].target_date!).getTime() + 7 * 86_400_000
    : today.getTime() + 30 * 86_400_000;
  const spanMs = Math.max(latestMs - earliestMs, 1);

  const positionPct = (dateMs: number) =>
    Math.min(100, Math.max(0, ((dateMs - earliestMs) / spanMs) * 100));

  const todayPct = positionPct(today.getTime());

  return (
    <div className="flex flex-col gap-6 p-4 overflow-auto">
      {/* Timeline header */}
      <div className="relative">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
          时间线
        </div>

        {/* Timeline axis */}
        <div className="relative h-2 rounded-full bg-muted/40">
          {/* Today marker */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-0.5 h-5 bg-brand rounded-full z-10"
            style={{ left: `${todayPct}%` }}
            title="今天"
          />
          {/* Goal markers */}
          {goalsWithDate.map((g) => {
            const ms = new Date(g.target_date!).getTime();
            const pct = positionPct(ms);
            const daysLeft = Math.ceil((ms - today.getTime()) / 86_400_000);
            const urgency = getUrgency(daysLeft);
            const color =
              urgency === "overdue"
                ? "bg-destructive"
                : urgency === "soon"
                  ? "bg-warning"
                  : urgency === "normal"
                    ? "bg-brand"
                    : "bg-muted-foreground";
            return (
              <div
                key={g.id}
                className={`absolute top-1/2 -translate-y-1/2 size-3 rounded-full ${color} ring-2 ring-background z-10`}
                style={{ left: `${pct}%`, transform: "translate(-50%, -50%)" }}
                title={`${g.title}: ${formatDaysLeft(daysLeft)}`}
              />
            );
          })}
        </div>

        {/* Date labels */}
        <div className="flex justify-between mt-1 text-[10px] text-muted-foreground">
          <span>{new Date(earliestMs).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}</span>
          <span className="text-brand font-medium">今天</span>
          <span>{new Date(latestMs).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}</span>
        </div>
      </div>

      {/* Goal rows */}
      <div className="space-y-2">
        {sorted.map((goal) => {
          const hasDate = !!goal.target_date;
          const daysLeft = hasDate
            ? Math.ceil((new Date(goal.target_date!).getTime() - today.getTime()) / 86_400_000)
            : null;
          const urgency = daysLeft !== null ? getUrgency(daysLeft) : "future";
          const dotColor =
            urgency === "overdue"
              ? "bg-destructive"
              : urgency === "soon"
                ? "bg-warning"
                : urgency === "normal"
                  ? "bg-brand"
                  : "bg-muted-foreground/40";

          // Progress bar width from completion_percent or status
          const progressPct =
            goal.status === "completed"
              ? 100
              : goal.status === "active"
                ? 30
                : 0;

          return (
            <div
              key={goal.id}
              className="flex items-center gap-3 rounded-xl bg-muted/20 p-3.5 hover:bg-muted/30 transition-colors"
            >
              {/* Status dot */}
              <div className={`size-2.5 rounded-full shrink-0 ${dotColor}`} />

              {/* Goal info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{goal.title}</p>
                  {goal.status === "completed" && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-success-muted text-success font-medium shrink-0">
                      完成
                    </span>
                  )}
                </div>
                {/* Progress bar */}
                {progressPct > 0 && (
                  <div className="mt-1.5 h-1 rounded-full bg-muted/50 overflow-hidden">
                    <div
                      className="h-full bg-brand rounded-full transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                )}
              </div>

              {/* Deadline */}
              <div className="shrink-0 text-right">
                {hasDate && daysLeft !== null ? (
                  <>
                    <p
                      className={`text-xs font-medium tabular-nums ${
                        urgency === "overdue"
                          ? "text-destructive"
                          : urgency === "soon"
                            ? "text-warning"
                            : "text-muted-foreground"
                      }`}
                    >
                      {formatDaysLeft(daysLeft)}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {new Date(goal.target_date!).toLocaleDateString("zh-CN", {
                        month: "short",
                        day: "numeric",
                      })}
                    </p>
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">无截止日期</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[11px] text-muted-foreground pt-2 border-t border-border/40">
        <div className="flex items-center gap-1.5">
          <div className="size-2 rounded-full bg-destructive" />
          <span>已逾期</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="size-2 rounded-full bg-warning" />
          <span>7天内</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="size-2 rounded-full bg-brand" />
          <span>30天内</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="size-2 rounded-full bg-muted-foreground/40" />
          <span>较远</span>
        </div>
      </div>
    </div>
  );
}
