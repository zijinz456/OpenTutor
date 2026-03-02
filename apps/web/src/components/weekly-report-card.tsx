"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { getWeeklyReport, type WeeklyReport } from "@/lib/api";
import { ShareReportButton } from "@/components/share-report-button";

function DeltaIndicator({ value, unit = "" }: { value: number; unit?: string }) {
  if (value > 0) return <span className="text-green-600 text-[11px] flex items-center gap-0.5"><span aria-hidden="true">{"\u2191"}</span>+{value}{unit}</span>;
  if (value < 0) return <span className="text-red-500 text-[11px] flex items-center gap-0.5"><span aria-hidden="true">{"\u2193"}</span>{value}{unit}</span>;
  return <span className="text-muted-foreground text-[11px] flex items-center gap-0.5"><span aria-hidden="true">{"\u2014"}</span>0{unit}</span>;
}

export function WeeklyReportCard() {
  const cardRef = useRef<HTMLDivElement>(null);
  const [report, setReport] = useState<WeeklyReport | null>(null);

  useEffect(() => {
    getWeeklyReport().then(setReport).catch(() => {});
  }, []);

  if (!report) return null;
  // Don't show if user has zero activity
  if (report.this_week.study_minutes === 0 && report.this_week.quiz_total === 0 && report.last_week.study_minutes === 0) {
    return null;
  }

  return (
    <div ref={cardRef} className="rounded-xl border border-border bg-gradient-to-r from-primary/5 to-purple-50 dark:to-purple-950/20 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-brand font-bold text-sm" aria-hidden="true">Report</span>
          <span className="text-sm font-semibold text-foreground">Weekly Report</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">
            {report.period.start} — {report.period.end}
          </span>
          <ShareReportButton targetRef={cardRef} compact />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-3">
        <div>
          <div className="flex items-center gap-1 text-muted-foreground text-[10px] uppercase tracking-wide">
            Study Time
          </div>
          <div className="text-lg font-semibold text-foreground mt-0.5">{report.this_week.study_minutes}m</div>
          <DeltaIndicator value={report.deltas.study_minutes} unit="m" />
        </div>
        <div>
          <div className="flex items-center gap-1 text-muted-foreground text-[10px] uppercase tracking-wide">
            Accuracy
          </div>
          <div className="text-lg font-semibold text-foreground mt-0.5">{report.this_week.accuracy}%</div>
          <DeltaIndicator value={report.deltas.accuracy} unit="%" />
        </div>
        <div>
          <div className="flex items-center gap-1 text-muted-foreground text-[10px] uppercase tracking-wide">
            Mastery
          </div>
          <div className="text-lg font-semibold text-foreground mt-0.5">{report.mastery_avg}%</div>
        </div>
      </div>

      {report.highlights.length > 0 && (
        <ul className="space-y-1 mb-3">
          {report.highlights.map((h, i) => (
            <li key={i} className="text-xs text-muted-foreground flex items-start gap-1.5">
              <span className="text-brand mt-px">{"\u2022"}</span>
              {h}
            </li>
          ))}
        </ul>
      )}

      <Link href="/analytics" className="text-xs text-brand font-medium hover:underline">
        View full analytics {"\u2192"}
      </Link>
    </div>
  );
}
