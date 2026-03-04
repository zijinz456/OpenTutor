"use client";

import {
  AreaChart,
  Area,
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

interface StudyTimeChartProps {
  data: TrendDataPoint[];
}

export function StudyTimeChart({ data }: StudyTimeChartProps) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="font-medium mb-4 text-foreground">Daily Study Time (last 30 days)</h2>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => String(v).slice(5)}
            />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              labelFormatter={(v) => String(v)}
              formatter={(value) => [`${value} min`, "Study Time"]}
            />
            <Area
              type="monotone"
              dataKey="study_minutes"
              stroke="hsl(var(--primary))"
              fill="hsl(var(--primary))"
              fillOpacity={0.2}
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
