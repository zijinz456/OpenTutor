"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, BookOpen, BrainCircuit, Clock, Loader2, RefreshCw, Target } from "lucide-react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getLearningOverview,
  getGlobalTrends,
  getMemoryStats,
  triggerConsolidation,
  type LearningOverview,
  type LearningTrends,
  type MemoryStats,
} from "@/lib/api";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { ShareReportButton } from "@/components/share-report-button";

const GAP_COLORS: Record<string, string> = {
  fundamental_gap: "#ef4444",
  transfer_gap: "#f59e0b",
  trap_vulnerability: "#8b5cf6",
  mastered: "#22c55e",
};

const ERROR_COLORS = ["#ef4444", "#f59e0b", "#3b82f6", "#8b5cf6", "#6b7280"];

export default function AnalyticsPage() {
  const router = useRouter();
  const statsRef = useRef<HTMLDivElement>(null);
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
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const gapEntries = Object.entries(overview?.gap_type_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const diagnosisEntries = Object.entries(overview?.diagnosis_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const errorEntries = Object.entries(overview?.error_category_breakdown ?? {}).sort((a, b) => b[1] - a[1]);
  const totalMinutes = overview?.total_study_minutes ?? 0;
  const trendData = trends?.trend ?? [];

  // Pie chart data for gap types
  const gapPieData = gapEntries.map(([name, value]) => ({
    name: name.replaceAll("_", " "),
    value,
    color: GAP_COLORS[name] || "#6b7280",
  }));

  // Pie chart data for error categories
  const errorPieData = errorEntries.map(([name, value], i) => ({
    name: name.replaceAll("_", " "),
    value,
    color: ERROR_COLORS[i % ERROR_COLORS.length],
  }));

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-3 flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/")} title="Back to dashboard">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold">Learning Analytics</h1>
        <div className="ml-auto">
          <ShareReportButton targetRef={statsRef} />
        </div>
      </header>

      <div ref={statsRef} className="max-w-6xl mx-auto p-6 space-y-6" data-testid="analytics-page">
        {/* Key Metrics */}
        <div className="grid md:grid-cols-4 gap-4">
          <MetricCard
            icon={<BookOpen className="h-4 w-4" />}
            label="Courses"
            value={String(overview?.total_courses ?? 0)}
          />
          <MetricCard
            icon={<Target className="h-4 w-4" />}
            label="Average Mastery"
            value={`${((overview?.average_mastery ?? 0) * 100).toFixed(0)}%`}
          />
          <MetricCard
            icon={<Clock className="h-4 w-4" />}
            label="Study Time"
            value={totalMinutes >= 60 ? `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m` : `${totalMinutes}m`}
          />
          <MetricCard
            icon={<BrainCircuit className="h-4 w-4" />}
            label="Quiz Questions"
            value={String(trendData.reduce((sum, d) => sum + d.quiz_total, 0))}
          />
        </div>

        {/* Charts Row */}
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Study Activity Area Chart */}
          <section className="rounded-xl border bg-card p-4">
            <h2 className="font-medium mb-4">Daily Study Time (last 30 days)</h2>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => String(v).slice(5)}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={(v) => String(v)}
                    formatter={(value) => [`${value} min`, "Study Time"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="study_minutes"
                    stroke="hsl(var(--primary))"
                    fill="hsl(var(--primary))"
                    fillOpacity={0.2}
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>

          {/* Quiz Accuracy Bar Chart */}
          <section className="rounded-xl border bg-card p-4">
            <h2 className="font-medium mb-4">Quiz Activity (last 30 days)</h2>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => String(v).slice(5)}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={(v) => String(v)}
                    formatter={(value, name) => [
                      value,
                      name === "quiz_correct" ? "Correct" : "Total",
                    ]}
                  />
                  <Bar dataKey="quiz_total" fill="#94a3b8" name="quiz_total" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="quiz_correct" fill="#22c55e" name="quiz_correct" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>

        {/* Pie Charts Row */}
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Gap Type Distribution */}
          <section className="rounded-xl border bg-card p-4">
            <h2 className="font-medium mb-4">Knowledge Gap Distribution</h2>
            {gapPieData.length > 0 ? (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={gapPieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      label={({ name, percent }) =>
                        `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                      }
                    >
                      {gapPieData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground py-8 text-center">No gap data yet</p>
            )}
          </section>

          {/* Error Category Distribution */}
          <section className="rounded-xl border bg-card p-4">
            <h2 className="font-medium mb-4">Error Category Breakdown</h2>
            {errorPieData.length > 0 ? (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={errorPieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={50}
                      outerRadius={80}
                      label={({ name, percent }) =>
                        `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                      }
                    >
                      {errorPieData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground py-8 text-center">No error data yet</p>
            )}
          </section>
        </div>

        <section className="rounded-xl border bg-card p-4">
          <h2 className="font-medium mb-4">Diagnosed Patterns</h2>
          <div className="flex flex-wrap gap-2" data-testid="analytics-breakdown-diagnoses">
            {diagnosisEntries.length > 0 ? (
              diagnosisEntries.map(([name, count]) => (
                <Badge key={name} variant="secondary" className="capitalize">
                  {name.replaceAll("_", " ")}: {count}
                </Badge>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No diagnosis data yet</p>
            )}
          </div>
        </section>

        {/* Memory Health */}
        {memStats && memStats.total > 0 && (
          <section className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-medium">Memory Health</h2>
              <Button
                variant="outline"
                size="sm"
                onClick={handleConsolidate}
                disabled={consolidating}
              >
                {consolidating ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <RefreshCw className="h-3 w-3 mr-1" />}
                Consolidate
              </Button>
            </div>
            <div className="grid sm:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-2xl font-semibold">{memStats.total}</div>
                <div className="text-xs text-muted-foreground">Total Memories</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-semibold">{(memStats.avg_importance * 100).toFixed(0)}%</div>
                <div className="text-xs text-muted-foreground">Avg Importance</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-semibold">{memStats.merged_count}</div>
                <div className="text-xs text-muted-foreground">Merged</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-semibold">{memStats.uncategorized}</div>
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
        )}

        {/* Course Summaries */}
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
