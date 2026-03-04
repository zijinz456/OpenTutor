import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { MemoryStats } from "@/lib/api";

interface MemoryHealthSectionProps {
  memStats: MemoryStats;
  consolidating: boolean;
  onConsolidate: () => void;
}

export function MemoryHealthSection({
  memStats,
  consolidating,
  onConsolidate,
}: MemoryHealthSectionProps) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-medium text-foreground">Memory Health</h2>
        <Button
          variant="outline"
          size="sm"
          onClick={onConsolidate}
          disabled={consolidating}
        >
          {consolidating ? "Consolidating..." : "Consolidate"}
        </Button>
      </div>
      <div className="grid sm:grid-cols-4 gap-4">
        <div className="text-center">
          <div className="text-2xl font-semibold text-foreground">{memStats.total}</div>
          <div className="text-xs text-muted-foreground">Total Memories</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-semibold text-foreground">{(memStats.avg_importance * 100).toFixed(0)}%</div>
          <div className="text-xs text-muted-foreground">Avg Importance</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-semibold text-foreground">{memStats.merged_count}</div>
          <div className="text-xs text-muted-foreground">Merged</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-semibold text-foreground">{memStats.uncategorized}</div>
          <div className="text-xs text-muted-foreground">Uncategorized</div>
        </div>
      </div>
      {Object.keys(memStats.by_type).length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {Object.entries(memStats.by_type).map(([type, count]) => (
            <Badge key={type} variant="secondary" className="capitalize">
              {type}: {count}
            </Badge>
          ))}
        </div>
      )}
    </section>
  );
}
