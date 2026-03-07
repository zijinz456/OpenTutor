"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { listStudyGoals, type StudyGoal } from "@/lib/api";

interface CalendarViewProps {
  courseId: string;
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  return new Date(year, month, 1).getDay();
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function CalendarView({ courseId }: CalendarViewProps) {
  const [goals, setGoals] = useState<StudyGoal[]>([]);
  const [currentMonth, setCurrentMonth] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });

  useEffect(() => {
    listStudyGoals(courseId)
      .then((g) => setGoals(g))
      .catch(() => {});
  }, [courseId]);

  const { year, month } = currentMonth;
  const daysInMonth = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfWeek(year, month);
  const today = new Date();
  const isCurrentMonth = today.getFullYear() === year && today.getMonth() === month;

  // Map dates to goals
  const dateGoals = useMemo(() => {
    const map = new Map<string, StudyGoal[]>();
    for (const goal of goals) {
      if (!goal.target_date) continue;
      const d = new Date(goal.target_date);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      const existing = map.get(key) ?? [];
      existing.push(goal);
      map.set(key, existing);
    }
    return map;
  }, [goals]);

  const prevMonth = () => {
    setCurrentMonth((prev) => {
      if (prev.month === 0) return { year: prev.year - 1, month: 11 };
      return { ...prev, month: prev.month - 1 };
    });
  };

  const nextMonth = () => {
    setCurrentMonth((prev) => {
      if (prev.month === 11) return { year: prev.year + 1, month: 0 };
      return { ...prev, month: prev.month + 1 };
    });
  };

  // Build calendar grid
  const cells: Array<{ day: number | null; goals: StudyGoal[]; isToday: boolean; isPast: boolean }> = [];
  // Leading empty cells
  for (let i = 0; i < firstDay; i++) {
    cells.push({ day: null, goals: [], isToday: false, isPast: false });
  }
  // Day cells
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${year}-${month}-${d}`;
    const dayGoals = dateGoals.get(key) ?? [];
    const cellDate = new Date(year, month, d);
    const isToday = isCurrentMonth && d === today.getDate();
    const isPast = cellDate < new Date(today.getFullYear(), today.getMonth(), today.getDate());
    cells.push({ day: d, goals: dayGoals, isToday, isPast });
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-4">
      {/* Month header */}
      <div className="flex items-center justify-between mb-4">
        <button type="button" onClick={prevMonth} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
          <ChevronLeft className="size-4" />
        </button>
        <h3 className="text-sm font-semibold text-foreground">
          {MONTH_NAMES[month]} {year}
        </h3>
        <button type="button" onClick={nextMonth} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
          <ChevronRight className="size-4" />
        </button>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {DAY_LABELS.map((d) => (
          <div key={d} className="text-center text-[10px] font-medium text-muted-foreground py-1">
            {d}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-1 flex-1">
        {cells.map((cell, i) => (
          <div
            key={i}
            className={`min-h-[48px] rounded-xl text-xs p-1.5 flex flex-col transition-colors ${
              cell.day === null
                ? "border-transparent"
                : cell.isToday
                  ? "border border-brand bg-brand-muted/30 card-shadow"
                  : cell.isPast
                    ? "bg-muted/20"
                    : "bg-muted/10 hover:bg-muted/30"
            }`}
          >
            {cell.day !== null && (
              <>
                <span className={`text-[11px] leading-none ${
                  cell.isToday ? "font-bold text-brand" : cell.isPast ? "text-muted-foreground" : "text-foreground"
                }`}>
                  {cell.day}
                </span>
                {cell.goals.map((g) => {
                  const daysLeft = Math.ceil(
                    (new Date(g.target_date!).getTime() - today.getTime()) / 86_400_000,
                  );
                  const urgencyClass =
                    daysLeft < 0 ? "bg-destructive/20 text-destructive"
                    : daysLeft <= 3 ? "bg-warning-muted text-warning"
                    : "bg-brand-muted text-brand";
                  return (
                    <div
                      key={g.id}
                      className={`mt-0.5 px-1 py-0.5 rounded-full text-[9px] leading-tight truncate ${urgencyClass}`}
                      title={g.title}
                    >
                      {g.title}
                    </div>
                  );
                })}
              </>
            )}
          </div>
        ))}
      </div>

      {/* Upcoming list below calendar */}
      {goals.filter((g) => g.target_date).length > 0 && (
        <div className="mt-4 border-t border-border/60 pt-3 space-y-1.5">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Upcoming</h4>
          {goals
            .filter((g) => g.target_date)
            .sort((a, b) => new Date(a.target_date!).getTime() - new Date(b.target_date!).getTime())
            .slice(0, 5)
            .map((g) => {
              const daysLeft = Math.ceil(
                (new Date(g.target_date!).getTime() - today.getTime()) / 86_400_000,
              );
              return (
                <div key={g.id} className="flex items-center gap-2 text-xs">
                  <span className={`tabular-nums shrink-0 w-12 text-right ${
                    daysLeft < 0 ? "text-destructive font-semibold" : daysLeft <= 3 ? "text-warning font-medium" : "text-muted-foreground"
                  }`}>
                    {daysLeft < 0 ? "Overdue" : daysLeft === 0 ? "Today" : `${daysLeft}d`}
                  </span>
                  <span className="truncate text-foreground">{g.title}</span>
                  <span className="text-muted-foreground shrink-0">{g.status}</span>
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}
