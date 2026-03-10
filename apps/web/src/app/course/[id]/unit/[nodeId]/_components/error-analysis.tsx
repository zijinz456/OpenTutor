import type { WrongAnswer } from "@/lib/api";
import type { ErrorPatternSummary } from "./unit-utils";

type TranslateFn = (key: string) => string;

export function ErrorAnalysis({ items, t }: { items: WrongAnswer[]; t: TranslateFn }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("unit.error.empty")}</p>;
  }
  return (
    <div className="space-y-3">
      {items.slice(0, 6).map((item) => (
        <div key={item.id} className="rounded-xl bg-muted/30 p-3.5">
          <p className="text-sm text-foreground">{item.question ?? t("unit.questionFallback")}</p>
          <div className="flex gap-4 mt-2 text-xs flex-wrap">
            <span className="text-destructive">{t("unit.error.yourAnswer")}: {item.user_answer || "\u2014"}</span>
            <span className="text-success">{t("unit.error.correctAnswer")}: {item.correct_answer ?? "\u2014"}</span>
          </div>
          {item.diagnosis ? (
            <p className="text-xs text-muted-foreground mt-1">{t("unit.error.diagnosis")}: {item.diagnosis}</p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function ErrorPatternSection({
  wrongAnswers,
  errorPatterns,
  t,
}: {
  wrongAnswers: WrongAnswer[];
  errorPatterns: ErrorPatternSummary;
  t: TranslateFn;
}) {
  return (
    <div className="rounded-2xl bg-card card-shadow p-4">
      <h2 className="text-base font-semibold">{t("unit.errorPattern.title")}</h2>
      <p className="text-xs text-muted-foreground mt-0.5">{t("unit.errorPattern.desc")}</p>

      {wrongAnswers.length === 0 ? (
        <p className="text-sm text-muted-foreground mt-3">{t("unit.errorPattern.empty")}</p>
      ) : (
        <div className="mt-3 space-y-3">
          <div>
            <p className="text-[11px] text-muted-foreground mb-1">{t("unit.errorPattern.diagnosis")}</p>
            <div className="flex flex-wrap gap-1.5">
              {errorPatterns.diagnoses.length > 0 ? errorPatterns.diagnoses.map((item) => (
                <span
                  key={`diag-${item.label}`}
                  className="text-[11px] px-2 py-1 rounded-full bg-destructive/10 text-destructive"
                >
                  {item.label} · {item.count}
                </span>
              )) : (
                <span className="text-[11px] text-muted-foreground">{t("unit.none")}</span>
              )}
            </div>
          </div>

          <div>
            <p className="text-[11px] text-muted-foreground mb-1">{t("unit.errorPattern.category")}</p>
            <div className="flex flex-wrap gap-1.5">
              {errorPatterns.categories.length > 0 ? errorPatterns.categories.map((item) => (
                <span
                  key={`cat-${item.label}`}
                  className="text-[11px] px-2 py-1 rounded-full bg-warning/10 text-warning"
                >
                  {item.label} · {item.count}
                </span>
              )) : (
                <span className="text-[11px] text-muted-foreground">{t("unit.none")}</span>
              )}
            </div>
          </div>

          <div>
            <p className="text-[11px] text-muted-foreground mb-1">{t("unit.errorPattern.knowledgePoint")}</p>
            <div className="flex flex-wrap gap-1.5">
              {errorPatterns.knowledgePoints.length > 0 ? errorPatterns.knowledgePoints.map((item) => (
                <span
                  key={`kp-${item.label}`}
                  className="text-[11px] px-2 py-1 rounded-full bg-brand/10 text-brand"
                >
                  {item.label} · {item.count}
                </span>
              )) : (
                <span className="text-[11px] text-muted-foreground">{t("unit.none")}</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
