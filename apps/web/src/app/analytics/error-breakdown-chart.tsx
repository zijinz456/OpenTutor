"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { ERROR_COLORS } from "./chart-colors";

interface PieDataEntry {
  name: string;
  value: number;
  color: string;
}

interface ErrorBreakdownChartProps {
  errorBreakdown: Record<string, number>;
}

function buildErrorPieData(errorBreakdown: Record<string, number>): PieDataEntry[] {
  return Object.entries(errorBreakdown)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value], i) => ({
      name: name.replaceAll("_", " "),
      value,
      color: ERROR_COLORS[i % ERROR_COLORS.length],
    }));
}

export function ErrorBreakdownChart({ errorBreakdown }: ErrorBreakdownChartProps) {
  const data = buildErrorPieData(errorBreakdown);

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="font-medium mb-4 text-foreground">Error Category Breakdown</h2>
      {data.length > 0 ? (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                label={({ name, percent }) =>
                  `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                }
              >
                {data.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground py-8 text-center">No error data yet</p>
      )}
    </section>
  );
}
