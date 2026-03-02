"use client";

import { type RefObject, useState } from "react";
import { toPng } from "html-to-image";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

interface ShareReportButtonProps {
  targetRef: RefObject<HTMLElement | null>;
  compact?: boolean;
}

export function ShareReportButton({ targetRef, compact }: ShareReportButtonProps) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const handleShare = async () => {
    const node = targetRef.current;
    if (!node || busy) return;

    setBusy(true);
    try {
      const dataUrl = await toPng(node, { pixelRatio: 2 });
      const res = await fetch(dataUrl);
      const blob = await res.blob();
      const file = new File([blob], "weekly-report.png", { type: "image/png" });

      if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: "My Weekly Learning Report" });
      } else {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
        toast.success("Copied report image to clipboard");
      }
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        toast.error("Failed to share report");
      }
    } finally {
      setBusy(false);
    }
  };

  const label = busy ? "..." : done ? "\u2713" : "Share";

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={compact ? "h-6 w-auto px-1 text-xs" : "h-7 text-xs px-2"}
      onClick={() => void handleShare()}
      disabled={busy}
      title="Share report"
    >
      <span className={busy ? "animate-pulse" : ""}>{label}</span>
    </Button>
  );
}
