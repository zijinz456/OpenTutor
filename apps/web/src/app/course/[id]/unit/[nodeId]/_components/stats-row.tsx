type TranslateFn = (key: string) => string;

interface StatsRowProps {
  subsectionCount: number;
  wrongAnswerCount: number;
  urgentReviewCount: number;
  t: TranslateFn;
}

export function StatsRow({ subsectionCount, wrongAnswerCount, urgentReviewCount, t }: StatsRowProps) {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="rounded-2xl bg-card card-shadow p-4">
        <p className="text-xs text-muted-foreground">{t("unit.subsections")}</p>
        <p className="text-2xl font-semibold mt-1">{subsectionCount}</p>
      </div>
      <div className="rounded-2xl bg-card card-shadow p-4">
        <p className="text-xs text-muted-foreground">{t("unit.wrongAnswers")}</p>
        <p className="text-2xl font-semibold mt-1">{wrongAnswerCount}</p>
      </div>
      <div className="rounded-2xl bg-card card-shadow p-4">
        <p className="text-xs text-muted-foreground">{t("unit.urgentReviews")}</p>
        <p className="text-2xl font-semibold mt-1">{urgentReviewCount}</p>
      </div>
    </section>
  );
}
