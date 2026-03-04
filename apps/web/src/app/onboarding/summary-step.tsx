import { useT } from "@/lib/i18n-context";
import { getSummaryLabel } from "./types";

interface SummaryStepProps {
  selections: Record<string, string>;
  optionLabels: Map<string, string>;
}

export function SummaryStep({ selections, optionLabels }: SummaryStepProps) {
  const t = useT();

  return (
    <div className="flex flex-col gap-4">
      <div className="w-full p-6 border border-border rounded-[10px] bg-muted flex flex-col gap-3">
        <span className="text-sm font-medium text-foreground">{t("onboarding.summary.title")}</span>
        {Object.entries(selections).map(([dimension, value]) => (
          <div key={dimension} className="flex items-center gap-2">
            <span className="text-success text-xs shrink-0">{"\u2713"}</span>
            <span className="text-[13px] text-muted-foreground">
              {getSummaryLabel(dimension, t)}:{" "}
              <span className="font-medium text-foreground">
                {optionLabels.get(`${dimension}:${value}`) ?? value.replace(/_/g, " ")}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="text-[13px] text-muted-foreground text-center">{t("onboarding.summary.later")}</p>
    </div>
  );
}
