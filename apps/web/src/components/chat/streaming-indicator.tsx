"use client";

/**
 * Three animated dots shown inline while the AI is generating a response.
 */
export function StreamingIndicator() {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-1" aria-label="AI is thinking">
      <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:0ms]" />
      <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
      <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
    </span>
  );
}
