"use client";

/**
 * `<MissBanner>` — Slice 3 Path B wrong-state wrap.
 *
 * Composes on top of the existing block-specific wrong-state UI rather
 * than replacing it (critic C6). Renders an amber-toned strip with the
 * canonical "Miss. Answer: {x}" copy (ТЗ §10 line 906) plus inline
 * pills: `<AddToReviewLink>` and `<ExplainStep>` in expanded form (the
 * miss state — auto-focused, per C1).
 *
 * Children slot underneath the banner so per-block details (diff, code
 * reveal, justification feedback, etc.) keep rendering exactly as they
 * did before. The pre-existing destructive-tinted result pane in each
 * block is what the children typically are; the banner just adds the
 * standard practice-surface affordances on top of it.
 *
 * Tokens: `border-warning/40 bg-warning/10` is the amber-on-near-black
 * pair already in use by `lab-exercise-block.tsx` (safety banner) and
 * defined in `globals.css` via `--warning: var(--thm-track-hacking)`.
 * No new palette colors are introduced.
 */

import type { ReactNode } from "react";
import { AddToReviewLink } from "./add-to-review-link";
import { ExplainStep } from "./explain-step";

export interface MissBannerProps {
  problemId: string;
  /** Optional course/track id for the "Add to review" deep-link. When
   *  omitted, the link is suppressed (some host surfaces don't yet have
   *  the courseId in scope; safer to hide than to ship a broken href). */
  courseId?: string;
  /** The reference answer surfaced from the server. May be a string,
   *  empty string, or null/undefined. We render a fallback dash when
   *  missing so the banner copy never reads "Miss. Answer: ". */
  revealedAnswer?: string | null;
  /** Existing wrong-state content (diff display, expected output,
   *  justification feedback, etc.). Slotted underneath the banner. */
  children?: ReactNode;
  className?: string;
}

export function MissBanner({
  problemId,
  courseId,
  revealedAnswer,
  children,
  className,
}: MissBannerProps) {
  const answerText =
    revealedAnswer && revealedAnswer.trim().length > 0 ? revealedAnswer : "—";

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid={`miss-banner-${problemId}`}
      className={`rounded-md border border-warning/40 bg-warning/10 p-3 ${
        className ?? ""
      }`.trim()}
    >
      <p
        className="text-sm font-medium text-warning whitespace-pre-wrap"
        data-testid={`miss-banner-copy-${problemId}`}
      >
        Miss. Answer: {answerText}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {courseId ? (
          <AddToReviewLink courseId={courseId} problemId={problemId} />
        ) : null}
      </div>

      {children ? <div className="mt-2">{children}</div> : null}

      <div className="mt-3">
        <ExplainStep problemId={problemId} correct={false} />
      </div>
    </div>
  );
}

export default MissBanner;
