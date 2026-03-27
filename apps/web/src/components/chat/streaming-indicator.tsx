"use client";

/**
 * Three animated dots shown inline while the AI is generating a response.
 */
interface StreamingIndicatorProps {
  phaseLabel?: string | null;
  hint?: string | null;
}

export function StreamingIndicator({ phaseLabel, hint }: StreamingIndicatorProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="inline-flex max-w-[85%] items-start gap-2 rounded-2xl bg-muted/30 px-3 py-2 animate-fade-in"
      aria-label="AI is thinking"
    >
      <span className="mt-1 inline-flex items-center gap-1.5">
        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:0ms]" />
        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:150ms]" />
        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40 [animation-delay:300ms]" />
      </span>
      {(phaseLabel || hint) ? (
        <span className="min-w-0">
          {phaseLabel ? <span className="block text-xs font-medium text-foreground/80">{phaseLabel}</span> : null}
          {hint ? <span className="block text-[11px] text-muted-foreground">{hint}</span> : null}
        </span>
      ) : null}
    </div>
  );
}
