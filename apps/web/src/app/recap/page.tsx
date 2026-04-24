"use client";

/**
 * `/recap` — "What you last learned" read-only listing (ADHD Phase 14 T4).
 *
 * Consumes `?concepts=a|b|c` produced by `<WelcomeBackModal>`. The pipe
 * separator survives URL encoding cleanly even when titles contain
 * spaces, commas, or punctuation.
 *
 * For this slice we render the titles only — no summary lookup. The
 * backend currently has no `content_nodes.summary` column, so deferring
 * the content-fetch is a deliberate plan decision (plan
 * `plan/adhd_ux_full_phase14.md:P2` — future enhancement).
 *
 * TODO(plan/adhd_ux_full_phase14.md:P2): once a concept-summary endpoint
 * exists, look each title up and surface the canonical definition in
 * place of the "completion message" placeholder below.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { useT } from "@/lib/i18n-context";

const MAX_CONCEPTS = 3;

function parseConcepts(raw: string | null): string[] {
  if (!raw) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const chunk of raw.split("|")) {
    const title = chunk.trim();
    if (!title) continue;
    if (seen.has(title)) continue;
    seen.add(title);
    out.push(title);
    if (out.length >= MAX_CONCEPTS) break;
  }
  return out;
}

export default function RecapPage() {
  const searchParams = useSearchParams();
  const t = useT();
  const concepts = useMemo(
    () => parseConcepts(searchParams.get("concepts")),
    [searchParams],
  );

  return (
    <div className="min-h-screen bg-background">
      <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-10 sm:px-6">
        <h1
          className="text-2xl font-bold tracking-tight text-foreground"
          data-testid="recap-title"
        >
          {t("recap.title")}
        </h1>

        {concepts.length === 0 ? (
          <p
            className="text-sm text-muted-foreground"
            data-testid="recap-empty"
          >
            {t("recap.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-3" data-testid="recap-list">
            {concepts.map((title) => (
              <li
                key={title}
                className="rounded-2xl bg-card px-5 py-4 card-shadow"
              >
                <h2 className="text-base font-semibold text-foreground">
                  {title}
                </h2>
              </li>
            ))}
          </ul>
        )}

        <Link
          href="/"
          className="text-sm text-brand hover:underline"
          data-testid="recap-back"
        >
          {t("recap.back")}
        </Link>
      </main>
    </div>
  );
}
