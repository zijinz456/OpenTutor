"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, BarChart3, Clock3, Minus, Target, Trophy } from "lucide-react";
import Link from "next/link";
import { getWeeklyReport, type WeeklyReport } from "@/lib/api";
import { ShareReportButton } from "@/components/share-report-button";

function DeltaIndicator({ value, unit = "" }: { value: number; unit?: string }) {
  if (value > 0) return <span className="text-green-600 text-[11px] flex items-center gap-0.5"><ArrowUp className="w-3 h-3" />+{value}{unit}</span>;
  if (value < 0) return <span className="text-red-500 text-[11px] flex items-center gap-0.5"><ArrowDown className="w-3 h-3" />{value}{unit}</span>;
  return <span className="text-muted-foreground text-[11px] flex items-center gap-0.5"><Minus className="w-3 h-3" />0{unit}</span>;
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
    <div ref={cardRef} className="rounded-xl border border-gray-200 bg-gradient-to-r from-indigo-50 to-purple-50 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Trophy className="w-4 h-4 text-indigo-600" />
          <span className="text-sm font-semibold text-gray-900">Weekly Report</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-400">
            {report.period.start} — {report.period.end}
          </span>
          <ShareReportButton targetRef={cardRef} compact />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-3">
        <div>
          <div className="flex items-center gap-1 text-gray-500 text-[10px] uppercase tracking-wide">
            <Clock3 className="w-3 h-3" /> Study Time
          </div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">{report.this_week.study_minutes}m</div>
          <DeltaIndicator value={report.deltas.study_minutes} unit="m" />
        </div>
        <div>
          <div className="flex items-center gap-1 text-gray-500 text-[10px] uppercase tracking-wide">
            <Target className="w-3 h-3" /> Accuracy
          </div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">{report.this_week.accuracy}%</div>
          <DeltaIndicator value={report.deltas.accuracy} unit="%" />
        </div>
        <div>
          <div className="flex items-center gap-1 text-gray-500 text-[10px] uppercase tracking-wide">
            <BarChart3 className="w-3 h-3" /> Mastery
          </div>
          <div className="text-lg font-semibold text-gray-900 mt-0.5">{report.mastery_avg}%</div>
        </div>
      </div>

      {report.highlights.length > 0 && (
        <ul className="space-y-1 mb-3">
          {report.highlights.map((h, i) => (
            <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
              <span className="text-indigo-500 mt-px">•</span>
              {h}
            </li>
          ))}
        </ul>
      )}

      <Link href="/analytics" className="text-xs text-indigo-600 font-medium hover:underline">
        View full analytics →
      </Link>
    </div>
  );
}
