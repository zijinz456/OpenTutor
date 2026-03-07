"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getLearningOverview,
  getGlobalTrends,
  getMemoryStats,
  triggerConsolidation,
  type LearningOverview,
  type LearningTrends,
  type MemoryStats,
} from "@/lib/api";
import { MetricCard } from "./metric-card";
import { StudyTimeChart } from "./study-time-chart";
import { QuizActivityChart } from "./quiz-activity-chart";
import { GapDistributionChart } from "./gap-distribution-chart";
import { ErrorBreakdownChart } from "./error-breakdown-chart";
import { DiagnosedPatterns } from "./diagnosed-patterns";
import { MemoryHealthSection } from "./memory-health-section";
import { CourseSummaries } from "./course-summaries";

export default function AnalyticsPage() {
  const router = useRouter();
  const [overview, setOverview] = useState<LearningOverview | null>(null);
  const [trends, setTrends] = useState<LearningTrends | null>(null);
  const [memStats, setMemStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [consolidating, setConsolidating] = useState(false);

  useEffect(() => {
    let cancelled = false;

    Promise.allSettled([getLearningOverview(), getGlobalTrends(30), getMemoryStats()])
      .then(([overviewResult, trendsResult, memoryResult]) => {
        if (cancelled) return;
        if (overviewResult.status === "fulfilled") {
          setOverview(overviewResult.value);
        }
        if (trendsResult.status === "fulfilled") {
          setTrends(trendsResult.value);
        }
        if (memoryResult.status === "fulfilled") {
          setMemStats(memoryResult.value);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleConsolidate = async () => {
    setConsolidating(true);
    try {
      await triggerConsolidation();
      const ms = await getMemoryStats();
      setMemStats(ms);
    } catch {
      // ignore
    } finally {
      setConsolidating(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <span className="text-muted-foreground animate-pulse">Loading...</span>
      </div>
    );
  }

  const totalMinutes = overview?.total_study_minutes ?? 0;
  const trendData = trends?.trend ?? [];

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/60 px-6 py-3 flex items-center gap-3 glass">
        <button
          type="button"
          onClick={() => router.push("/")}
          className="text-sm text-muted-foreground hover:text-foreground"
          title="Back to dashboard"
        >
          &larr; Back
        </button>
        <h1 className="text-lg font-semibold text-foreground">Learning Analytics</h1>
        <div className="ml-auto" />
      </header>

      <div className="max-w-6xl mx-auto p-6 space-y-6" data-testid="analytics-page">
        {/* Key Metrics */}
        <div className="grid md:grid-cols-4 gap-4">
          <MetricCard
            label="Courses"
            value={String(overview?.total_courses ?? 0)}
          />
          <MetricCard
            label="Average Mastery"
            value={`${((overview?.average_mastery ?? 0) * 100).toFixed(0)}%`}
          />
          <MetricCard
            label="Study Time"
            value={totalMinutes >= 60 ? `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m` : `${totalMinutes}m`}
          />
          <MetricCard
            label="Quiz Questions"
            value={String(trendData.reduce((sum, d) => sum + d.quiz_total, 0))}
          />
        </div>

        {/* Charts Row */}
        <div className="grid lg:grid-cols-2 gap-6">
          <StudyTimeChart data={trendData} />
          <QuizActivityChart data={trendData} />
        </div>

        {/* Pie Charts Row */}
        <div className="grid lg:grid-cols-2 gap-6">
          <GapDistributionChart gapBreakdown={overview?.gap_type_breakdown ?? {}} />
          <ErrorBreakdownChart errorBreakdown={overview?.error_category_breakdown ?? {}} />
        </div>

        <DiagnosedPatterns diagnosisBreakdown={overview?.diagnosis_breakdown ?? {}} />

        {/* Memory Health */}
        {memStats && memStats.total > 0 && (
          <MemoryHealthSection
            memStats={memStats}
            consolidating={consolidating}
            onConsolidate={handleConsolidate}
          />
        )}

        {/* Course Summaries */}
        <CourseSummaries courseSummaries={overview?.course_summaries ?? []} />
      </div>
    </div>
  );
}
