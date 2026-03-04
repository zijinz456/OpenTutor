interface MetricCardProps {
  label: string;
  value: string;
}

export function MetricCard({ label, value }: MetricCardProps) {
  return (
    <div
      className="rounded-xl border border-border bg-card p-4"
      data-testid={`analytics-metric-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <div className="text-sm text-muted-foreground mb-2">{label}</div>
      <div className="text-2xl font-semibold text-foreground">{value}</div>
    </div>
  );
}
