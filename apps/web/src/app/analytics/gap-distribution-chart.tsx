"use client";

import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { GAP_COLORS } from "./chart-colors";

interface PieDataEntry {
  name: string;
  value: number;
  color: string;
}

interface GapDistributionChartProps {
  gapBreakdown: Record<string, number>;
}

function buildGapPieData(gapBreakdown: Record<string, number>): PieDataEntry[] {
  return Object.entries(gapBreakdown)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({
      name: name.replaceAll("_", " "),
      value,
      color: GAP_COLORS[name] || "var(--color-muted-foreground, #a3a3a3)",
    }));
}

export function GapDistributionChart({ gapBreakdown }: GapDistributionChartProps) {
  const data = buildGapPieData(gapBreakdown);

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="font-medium mb-4 text-foreground">Knowledge Gap Distribution</h2>
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
        <p className="text-sm text-muted-foreground py-8 text-center">No gap data yet</p>
      )}
    </section>
  );
}
