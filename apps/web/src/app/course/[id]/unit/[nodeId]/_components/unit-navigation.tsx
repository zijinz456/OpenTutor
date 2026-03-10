import Link from "next/link";
import type { ContentNode } from "@/lib/api";

type TranslateFn = (key: string) => string;
type TranslateFormatFn = (key: string, vars?: Record<string, string | number | null | undefined>) => string;

interface UnitNavigationProps {
  courseId: string;
  nodePath: ContentNode[];
  parentNode: ContentNode | null;
  siblingNodes: ContentNode[];
  focusTerms: string[];
  wrongAnswerCount: number;
  reviewItemCount: number;
  t: TranslateFn;
  tf: TranslateFormatFn;
}

export function UnitNavigation({
  courseId,
  nodePath,
  parentNode,
  siblingNodes,
  focusTerms,
  wrongAnswerCount,
  reviewItemCount,
  t,
  tf,
}: UnitNavigationProps) {
  return (
    <section className="rounded-2xl bg-card card-shadow p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">{t("unit.path")}:</span>
        {nodePath.map((item, idx) => (
          <span key={item.id} className="inline-flex items-center gap-2">
            {idx > 0 ? <span className="text-muted-foreground">/</span> : null}
            {idx === nodePath.length - 1 ? (
              <span className="font-medium text-foreground">{item.title}</span>
            ) : (
              <Link
                href={`/course/${courseId}/unit/${item.id}`}
                className="text-brand hover:underline"
              >
                {item.title}
              </Link>
            )}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-xl bg-muted/30 p-3.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            {t("unit.parentSiblings")}
          </p>
          {parentNode ? (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {t("unit.parent")}:{" "}
                <Link href={`/course/${courseId}/unit/${parentNode.id}`} className="text-brand hover:underline">
                  {parentNode.title}
                </Link>
              </p>
              {siblingNodes.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {siblingNodes.slice(0, 8).map((sibling) => (
                    <Link
                      key={sibling.id}
                      href={`/course/${courseId}/unit/${sibling.id}`}
                      className="text-[11px] px-2 py-1 rounded-full bg-muted text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {sibling.title}
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{t("unit.noSiblings")}</p>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t("unit.topLevel")}</p>
          )}
        </div>

        <div className="rounded-xl bg-muted/30 p-3.5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
            {t("unit.conceptSignals")}
          </p>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {focusTerms.slice(0, 10).map((term) => (
              <span key={term} className="text-[11px] px-2 py-1 rounded-full bg-brand/10 text-brand">
                {term}
              </span>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {tf("unit.matchedSignals", { wrong: wrongAnswerCount, mastery: reviewItemCount })}
          </p>
        </div>
      </div>
    </section>
  );
}

export function SubsectionsNav({
  courseId,
  subsections,
  t,
}: {
  courseId: string;
  subsections: ContentNode[];
  t: TranslateFn;
}) {
  return (
    <section className="rounded-2xl bg-card card-shadow p-5">
      <h2 className="text-lg font-semibold mb-4">{t("unit.subsections")}</h2>
      <div className="flex flex-col gap-2">
        {subsections.map((child) => (
          <Link
            key={child.id}
            href={`/course/${courseId}/unit/${child.id}`}
            className="flex items-center gap-3 p-3.5 rounded-xl bg-muted/30 hover:bg-accent/50 transition-colors text-sm"
          >
            <span className="text-foreground">{child.title}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
