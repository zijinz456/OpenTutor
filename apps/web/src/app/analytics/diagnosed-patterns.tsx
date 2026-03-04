import { Badge } from "@/components/ui/badge";

interface DiagnosedPatternsProps {
  diagnosisBreakdown: Record<string, number>;
}

export function DiagnosedPatterns({ diagnosisBreakdown }: DiagnosedPatternsProps) {
  const entries = Object.entries(diagnosisBreakdown).sort((a, b) => b[1] - a[1]);

  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h2 className="font-medium mb-4 text-foreground">Diagnosed Patterns</h2>
      <div className="flex flex-wrap gap-2" data-testid="analytics-breakdown-diagnoses">
        {entries.length > 0 ? (
          entries.map(([name, count]) => (
            <Badge key={name} variant="secondary" className="capitalize">
              {name.replaceAll("_", " ")}: {count}
            </Badge>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">No diagnosis data yet</p>
        )}
      </div>
    </section>
  );
}
