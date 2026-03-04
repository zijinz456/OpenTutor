"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface TrendDataPoint {
  date: string;
  study_minutes: number;
  quiz_total: number;
  quiz_correct: number;
  accuracy: number | null;
}

interface QuizActivityChartProps {
  data: TrendDataPoint[];
}

export function QuizActivityChart({ data }: QuizActivityChartProps) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="font-medium mb-4 text-foreground">Quiz Activity (last 30 days)</h2>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => String(v).slice(5)}
            />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              labelFormatter={(v) => String(v)}
              formatter={(value, name) => [
                value,
                name === "quiz_correct" ? "Correct" : "Total",
              ]}
            />
            <Bar dataKey="quiz_total" fill="var(--color-muted-foreground, #a3a3a3)" name="quiz_total" radius={[2, 2, 0, 0]} />
            <Bar dataKey="quiz_correct" fill="var(--color-success, #404040)" name="quiz_correct" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
