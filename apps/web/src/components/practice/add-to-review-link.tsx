"use client";

/**
 * `<AddToReviewLink>` — Slice 3 Path B.
 *
 * Pill-styled anchor that points at the existing wrong-answers review
 * surface, scoped to a single problem id. The server-side
 * `routers/quiz_submission.py` already auto-creates a `WrongAnswer` row
 * on every miss (lines 444-459) — this link is *navigation only*, no
 * mutation, no extra request. Per ТЗ §11 rule 11: amber border miss
 * pane gets an "Add to review" affordance.
 *
 * Copy is fixed at "Add to review" — calm field-coach tone (§10), no
 * exclamation, no emoji, verb-first.
 */

import Link from "next/link";

export interface AddToReviewLinkProps {
  /** The course/track id used to scope the wrong-answers page. */
  courseId: string;
  /** The problem id to deep-link to. */
  problemId: string;
  className?: string;
}

export function AddToReviewLink({
  courseId,
  problemId,
  className,
}: AddToReviewLinkProps) {
  // Canonical existing route: /course/[id]/wrong-answers (ТЗ §9 line 843
  // marks /course/* as soft-deprecated but live for deep-links). Server
  // already creates the WrongAnswer row on miss; this is navigation-only.
  const href = `/course/${encodeURIComponent(courseId)}/wrong-answers?problem=${encodeURIComponent(problemId)}`;
  return (
    <Link
      href={href}
      data-testid={`add-to-review-link-${problemId}`}
      className={`inline-flex items-center rounded-full border border-border/60 bg-muted/30 px-3 py-1 text-[11px] font-medium text-muted-foreground hover:border-primary/50 ${
        className ?? ""
      }`.trim()}
    >
      Add to review
    </Link>
  );
}

export default AddToReviewLink;
