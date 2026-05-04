/**
 * `<PageShell>` — Visual Shell Phase 1.5 (Option A) primitive.
 *
 * Single source of truth for the canonical outer-page wrapper:
 *   `mx-auto w-full max-w-shell px-4 sm:px-6 lg:px-8`
 *
 * Used by `TopBar` and the routed pages (dashboard, /tracks,
 * /tracks/[slug], /profile/badges) so the top bar's content lines up
 * with the page content underneath at any viewport ≥1440px. Before
 * this primitive existed, TopBar capped at `max-w-7xl` (1280px) while
 * the pages used `max-w-[1600px]`, creating a ~160px right-edge
 * mismatch on widescreen monitors.
 *
 * Renders a plain `<div>` — NOT `<main>` — because `app/layout.tsx`
 * already provides the single page-level `<main id="main-content">`
 * landmark. Wrapping again would nest `<main>` (a11y violation).
 * Pages that previously used `<main className="…max-w-[1600px]…">`
 * have been migrated to `<PageShell>` so the underlying tag is
 * `<div>`.
 *
 * Pass-through props: `data-testid`, `aria-*`, etc. via `...rest`
 * so existing shell test ids (`dashboard-shell`, `tracks-shell`,
 * `path-detail-shell`, `profile-badges-page`) keep resolving.
 *
 * NOT used by `/tracks/[slug]/missions/[missionId]` — that page is
 * intentionally narrower (`max-w-7xl`, 1280px) for the 3-pane mission
 * layout. Out of Phase 1.5 scope; do not migrate.
 */

import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PageShellProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Extra Tailwind classes appended after the canonical shell classes
   *  (use for vertical padding, gap, flex layout — not for width). */
  className?: string;
}

export function PageShell({ children, className, ...rest }: PageShellProps) {
  return (
    <div
      {...rest}
      className={cn(
        "mx-auto w-full max-w-shell px-4 sm:px-6 lg:px-8",
        className,
      )}
    >
      {children}
    </div>
  );
}
