"use client";

import type { ConfusionPair } from "@/lib/api";

interface ConfusionPairsProps {
  pairs: ConfusionPair[];
}

export function ConfusionPairs({ pairs }: ConfusionPairsProps) {
  if (pairs.length === 0) return null;

  return (
    <div className="space-y-3" data-testid="confusion-pairs">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        Confused Concepts
      </h4>
      {pairs.slice(0, 5).map((pair) => (
        <div
          key={`${pair.concept_a}-${pair.concept_b}`}
          className="rounded-2xl border border-warning/30 bg-warning-muted/10 p-3.5"
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <p className="text-xs font-semibold text-foreground">{pair.concept_a}</p>
              {pair.description_a ? (
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  {pair.description_a}
                </p>
              ) : null}
            </div>
            <div className="space-y-1">
              <p className="text-xs font-semibold text-foreground">{pair.concept_b}</p>
              {pair.description_b ? (
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  {pair.description_b}
                </p>
              ) : null}
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground mt-2">
            Confused {pair.weight}× — review both concepts side by side
          </p>
        </div>
      ))}
    </div>
  );
}
