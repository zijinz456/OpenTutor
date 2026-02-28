"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, BarChart3, BookOpen, BrainCircuit, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getLearningOverview, type LearningOverview } from "@/lib/api";

export default function AnalyticsPage() {
  const router = useRouter();
  const [overview, setOverview] = useState<LearningOverview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getLearningOverview()
      .then(setOverview)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const gapEntries = Object.entries(overview?.gap_type_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const diagnosisEntries = Object.entries(overview?.diagnosis_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const errorEntries = Object.entries(overview?.error_category_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const totalMinutes = overview?.total_study_minutes ?? 0;

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-3 flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold">Learning Analytics</h1>
      </header>

      <div className="max-w-5xl mx-auto p-6 space-y-6" data-testid="analytics-page">
        <div className="grid md:grid-cols-4 gap-4">
          <MetricCard
            icon={<BookOpen className="h-4 w-4" />}
            label="Courses"
            value={String(overview?.total_courses ?? 0)}
          />
          <MetricCard
            icon={<BarChart3 className="h-4 w-4" />}
            label="Average Mastery"
            value={`${((overview?.average_mastery ?? 0) * 100).toFixed(0)}%`}
          />
          <MetricCard
            icon={<BrainCircuit className="h-4 w-4" />}
            label="Study Time"
            value={totalMinutes >= 60 ? `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m` : `${totalMinutes}m`}
          />
          <MetricCard
            icon={<BarChart3 className="h-4 w-4" />}
            label="Diagnosed Errors"
            value={String(diagnosisEntries.reduce((sum, [, count]) => sum + count, 0))}
          />
        </div>

        <div className="grid lg:grid-cols-3 gap-4">
          <BreakdownCard title="Gap Types" entries={gapEntries} />
          <BreakdownCard title="Diagnoses" entries={diagnosisEntries} />
          <BreakdownCard title="Error Categories" entries={errorEntries} />
        </div>

        <section className="rounded-xl border bg-card" data-testid="analytics-course-summaries">
          <div className="px-4 py-3 border-b">
            <h2 className="font-medium">Course Summaries</h2>
          </div>
          <div className="divide-y">
            {(overview?.course_summaries ?? []).map((course) => (
              <div
                key={course.course_id}
                className="p-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between"
                data-testid={`analytics-course-${course.course_id}`}
              >
                <div>
                  <h3 className="font-medium">{course.course_name}</h3>
                  <p className="text-sm text-muted-foreground">
                    Mastery {(course.average_mastery * 100).toFixed(0)}% · Study {course.study_minutes}m · Wrong answers {course.wrong_answers}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(course.gap_types).map(([gap, count]) => (
                    <Badge key={gap} variant="secondary" className="capitalize">
                      {gap.replaceAll("_", " ")}: {count}
                    </Badge>
                  ))}
                  {course.diagnosed_count > 0 && (
                    <Badge variant="outline">Diagnosed: {course.diagnosed_count}</Badge>
                  )}
                </div>
              </div>
            ))}
            {(overview?.course_summaries ?? []).length === 0 && (
              <div className="p-8 text-center text-sm text-muted-foreground">
                No learning analytics yet. Start practicing in a course first.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function MetricCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-xl border bg-card p-4" data-testid={`analytics-metric-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="flex items-center gap-2 text-muted-foreground text-sm mb-2">
        {icon}
        <span>{label}</span>
      </div>
      <div className="text-2xl font-semibold">{value}</div>
    </div>
  );
}

function BreakdownCard({ title, entries }: { title: string; entries: Array<[string, number]> }) {
  return (
    <section className="rounded-xl border bg-card p-4" data-testid={`analytics-breakdown-${title.toLowerCase().replace(/\s+/g, "-")}`}>
      <h2 className="font-medium mb-3">{title}</h2>
      <div className="flex flex-wrap gap-2">
        {entries.length > 0 ? entries.map(([label, count]) => (
          <Badge key={label} variant="secondary" className="capitalize">
            {label.replaceAll("_", " ")}: {count}
          </Badge>
        )) : (
          <span className="text-sm text-muted-foreground">No data yet</span>
        )}
      </div>
    </section>
  );
}
