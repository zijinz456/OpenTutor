/**
 * `<MissionHeader>` — Slice 2 mission page header strip.
 *
 * One-line breadcrumb `Tracks / {path_title} / {mission_title}` on the
 * left; difficulty/ETA/module chips on the right. Pure presentation —
 * no data fetching, no interactivity beyond the breadcrumb links.
 *
 * Copy per ТЗ §10:
 *   - No arrow glyphs in text (the breadcrumb separator is `·`, which
 *     visually reads as a soft divider and dodges rule 6's "no `→`").
 *   - Numbers bare: difficulty shown as N/5, eta shown as "NN min".
 *   - No exclamation, no emoji.
 *
 * Testid surface: `mission-header` on the outer `<header>`. Chips are
 * hidden from the test tree when their field is null (so tests can
 * assert presence vs absence without brittle attribute lookups).
 */

import Link from "next/link";

export interface MissionHeaderProps {
  pathSlug: string;
  pathTitle: string;
  missionTitle: string;
  difficulty: number | null;
  etaMinutes: number | null;
  moduleLabel: string | null;
}

export function MissionHeader({
  pathSlug,
  pathTitle,
  missionTitle,
  difficulty,
  etaMinutes,
  moduleLabel,
}: MissionHeaderProps) {
  return (
    <header
      data-testid="mission-header"
      className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3"
    >
      <nav
        aria-label="Breadcrumb"
        className="flex items-center gap-2 text-xs text-[var(--text-muted)]"
      >
        <Link
          href="/tracks"
          className="hover:text-[var(--text-primary)] transition-colors"
          data-testid="mission-header-breadcrumb-tracks"
        >
          Tracks
        </Link>
        <span aria-hidden="true">·</span>
        <Link
          href={`/tracks/${pathSlug}`}
          className="hover:text-[var(--text-primary)] transition-colors truncate max-w-[16rem]"
          data-testid="mission-header-breadcrumb-path"
        >
          {pathTitle}
        </Link>
        <span aria-hidden="true">·</span>
        <span
          className="text-[var(--text-primary)] truncate max-w-[20rem]"
          data-testid="mission-header-breadcrumb-mission"
        >
          {missionTitle}
        </span>
      </nav>

      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.04em] text-[var(--text-muted)]">
        {moduleLabel ? (
          <span
            data-testid="mission-header-chip-module"
            className="rounded-sm bg-[var(--surface-pressed,rgba(255,255,255,0.06))] px-2 py-0.5"
          >
            {moduleLabel}
          </span>
        ) : null}
        {difficulty !== null ? (
          <span
            data-testid="mission-header-chip-difficulty"
            className="rounded-sm bg-[var(--surface-pressed,rgba(255,255,255,0.06))] px-2 py-0.5 tabular-nums"
            aria-label={`Difficulty ${difficulty} of 5`}
          >
            {difficulty}/5
          </span>
        ) : null}
        {etaMinutes !== null ? (
          <span
            data-testid="mission-header-chip-eta"
            className="rounded-sm bg-[var(--surface-pressed,rgba(255,255,255,0.06))] px-2 py-0.5 tabular-nums"
          >
            {etaMinutes} min
          </span>
        ) : null}
      </div>
    </header>
  );
}
