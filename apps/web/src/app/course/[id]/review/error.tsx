"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md px-6">
        <h2 className="text-lg font-semibold mb-2">Failed to load review</h2>
        <p className="text-sm text-muted-foreground mb-4">
          {error.message || "Could not load your review session. Please try again."}
        </p>
        <button
          onClick={reset}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
