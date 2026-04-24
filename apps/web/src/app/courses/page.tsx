"use client";

/**
 * `/courses` — drill course list (Phase 16c T9).
 *
 * Lists every compiled drill course from ``GET /api/drills/courses``.
 * Each course is a full-card `<Link>` routing to `/courses/{slug}`. No
 * aggregate progress here (progress is learner-scoped and shown at the
 * course TOC level in a later pass).
 *
 * Data flow
 * ---------
 * Mount → ``listDrillCourses()`` → render card list. Network errors
 * already surface a toast via the shared ``request()`` wrapper — we
 * still show an inline retry button so the user has a stateful recovery
 * path without reloading the tab.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { listDrillCourses, type DrillCourseOut } from "@/lib/api";

export default function DrillCoursesPage() {
  const [data, setData] = useState<DrillCourseOut[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    let cancelled = false;
    listDrillCourses()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError("Не вдалось завантажити — спробуй ще раз");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const cancel = load();
    return cancel;
  }, [load]);

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            Home
          </Link>
          <h1 className="font-display mt-2 text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            Курси та дрилі
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Практика спочатку. Обери курс і почни дрил.
          </p>
        </div>

        {loading && (
          <div className="space-y-3" data-testid="drill-courses-loading">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-24 rounded-2xl bg-muted/40 animate-pulse"
              />
            ))}
          </div>
        )}

        {!loading && error && (
          <div
            role="alert"
            data-testid="drill-courses-error"
            className="rounded-2xl bg-destructive/5 px-5 py-4 text-sm text-destructive card-shadow"
          >
            <p>{error}</p>
            <button
              type="button"
              onClick={load}
              className="mt-2 rounded-full border border-destructive/40 bg-destructive/10 px-3 py-1 text-xs font-medium text-destructive hover:bg-destructive/20 transition-colors"
            >
              Спробувати ще раз
            </button>
          </div>
        )}

        {!loading && !error && data && (
          <div className="space-y-3" data-testid="drill-courses-list">
            {data.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Поки що нічого. Додай курс через{" "}
                <code className="rounded bg-muted/50 px-1 py-0.5 text-xs">
                  scripts/transpile_drills.py
                </code>
                .
              </p>
            ) : (
              data.map((course) => (
                <Link
                  key={course.id}
                  href={`/courses/${course.slug}`}
                  data-testid={`drill-course-card-${course.slug}`}
                  className="block rounded-2xl bg-card p-5 card-shadow hover:bg-muted/30 transition-colors"
                >
                  <h2 className="text-base font-semibold text-foreground">
                    {course.title}
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {course.module_count} модулів
                    {course.estimated_hours != null
                      ? ` · ~${course.estimated_hours}г`
                      : ""}
                  </p>
                  {course.description && (
                    <p className="mt-2 text-sm text-muted-foreground line-clamp-2">
                      {course.description}
                    </p>
                  )}
                </Link>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
