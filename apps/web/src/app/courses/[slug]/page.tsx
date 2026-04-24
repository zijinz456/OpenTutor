"use client";

/**
 * `/courses/[slug]` — full TOC for one drill course (Phase 16c T9).
 *
 * Loads ``DrillCourseTOC`` — course metadata, modules in ``order_index``
 * order, and each module's drills inline. Every drill row is a `<Link>`
 * routing to `/practice/{drill.id}` where the actual runner lives.
 *
 * 404 handling
 * ------------
 * The backend returns 404 when a slug is unknown or when the course has
 * no modules yet. The shared ``request()`` wrapper throws ``ApiError``
 * with ``status === 404``; we branch on the status to render the
 * "not seeded yet" copy instead of the generic error.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import {
  ApiError,
  getDrillCourseTOC,
  type DrillCourseTOC,
  type DrillOut,
} from "@/lib/api";

/** Difficulty pill palette — 1=green (easy), 2=amber, 3=red. */
const DIFFICULTY_STYLES: Record<number, string> = {
  1: "bg-emerald-500/10 text-emerald-700 border-emerald-500/40",
  2: "bg-amber-500/10 text-amber-700 border-amber-500/40",
  3: "bg-red-500/10 text-red-700 border-red-500/40",
};

function DrillRow({ drill }: { drill: DrillOut }) {
  const badgeClass =
    DIFFICULTY_STYLES[drill.difficulty_layer] ??
    "bg-muted/50 text-muted-foreground border-border";

  return (
    <Link
      href={`/practice/${drill.id}`}
      data-testid={`drill-row-${drill.slug}`}
      className="block rounded-xl bg-card p-4 card-shadow hover:bg-muted/30 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground tabular-nums">
              {String(drill.order_index).padStart(2, "0")}
            </span>
            <h3 className="text-sm font-medium text-foreground truncate">
              {drill.title}
            </h3>
          </div>
          {drill.skill_tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {drill.skill_tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="shrink-0 flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground tabular-nums">
            ~{drill.time_budget_min} хв
          </span>
          <span
            className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}
          >
            L{drill.difficulty_layer}
          </span>
        </div>
      </div>
    </Link>
  );
}

function DrillCourseTOCContent() {
  const params = useParams();
  const slugParam = params?.slug;
  const slug = Array.isArray(slugParam) ? slugParam[0] : slugParam;

  const [data, setData] = useState<DrillCourseTOC | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(() => {
    if (!slug) return () => {};
    setLoading(true);
    setError(null);
    setNotFound(false);
    let cancelled = false;
    getDrillCourseTOC(slug)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError("Не вдалось завантажити — спробуй ще раз");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    const cancel = load();
    return cancel;
  }, [load]);

  return (
    <div className="min-h-screen bg-background py-8 px-4">
      <div className="mx-auto max-w-3xl space-y-6">
        <div>
          <Link
            href="/courses"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="size-3.5" />
            Усі курси
          </Link>
        </div>

        {loading && (
          <div className="space-y-3" data-testid="drill-course-loading">
            <div className="h-8 w-64 rounded bg-muted/40 animate-pulse" />
            <div className="h-4 w-48 rounded bg-muted/40 animate-pulse" />
            <div className="space-y-2 pt-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-16 rounded-xl bg-muted/40 animate-pulse"
                />
              ))}
            </div>
          </div>
        )}

        {!loading && notFound && (
          <div
            role="alert"
            data-testid="drill-course-not-found"
            className="rounded-2xl bg-muted/30 px-5 py-4 text-sm text-muted-foreground card-shadow"
          >
            <p>
              Курс не знайдено. Можливо, ще не засіяний з{" "}
              <code className="rounded bg-muted/50 px-1 py-0.5 text-xs">
                content/drills/
              </code>
              .
            </p>
            <Link
              href="/courses"
              className="mt-2 inline-block text-xs text-foreground underline"
            >
              До списку курсів
            </Link>
          </div>
        )}

        {!loading && error && !notFound && (
          <div
            role="alert"
            data-testid="drill-course-error"
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

        {!loading && !error && !notFound && data && (
          <>
            <div>
              <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
                {data.title}
              </h1>
              {data.description && (
                <p className="mt-2 text-sm text-muted-foreground">
                  {data.description}
                </p>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                {data.module_count} модулів
                {data.estimated_hours != null
                  ? ` · ~${data.estimated_hours}г`
                  : ""}
                {" · "}
                <span className="font-mono">{data.source}</span>
              </p>
            </div>

            <div className="space-y-6" data-testid="drill-course-modules">
              {data.modules.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  У цьому курсі ще немає модулів.
                </p>
              ) : (
                data.modules.map((module) => (
                  <section
                    key={module.id}
                    data-testid={`drill-module-${module.slug}`}
                    className="space-y-2"
                  >
                    <div>
                      <h2 className="text-sm font-semibold text-foreground">
                        {String(module.order_index).padStart(2, "0")}.{" "}
                        {module.title}
                      </h2>
                      {module.outcome && (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {module.outcome}
                        </p>
                      )}
                    </div>
                    <div className="space-y-2">
                      {module.drills.length === 0 ? (
                        <p className="text-xs text-muted-foreground">
                          У цьому модулі немає дрилів.
                        </p>
                      ) : (
                        module.drills.map((drill) => (
                          <DrillRow key={drill.id} drill={drill} />
                        ))
                      )}
                    </div>
                  </section>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function DrillCourseTOCPage() {
  // Wrap in Suspense so ``useParams()`` doesn't bust Next 16's prerender
  // pass, mirroring the `/tracks/[slug]` convention.
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <DrillCourseTOCContent />
    </Suspense>
  );
}
