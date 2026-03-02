"use client";

import { type RefObject, useState } from "react";
import { Check, Loader2, Share2 } from "lucide-react";
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

  const Icon = busy ? Loader2 : done ? Check : Share2;

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={compact ? "h-6 w-6 p-0" : "h-7 text-xs px-2"}
      onClick={() => void handleShare()}
      disabled={busy}
      title="Share report"
    >
      <Icon className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
      {!compact && <span className="ml-1">Share</span>}
    </Button>
  );
}
