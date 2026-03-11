"use client";

import { useCallback, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { scrapeUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n-context";
import { toast } from "sonner";
import { Link, Loader2 } from "lucide-react";

interface UrlScrapePopoverProps {
  courseId: string;
  disabled: boolean;
  onScraped: () => void;
  onScrapingChange?: (isScraping: boolean) => void;
}

/**
 * Button with popover for entering a URL to scrape and add to course materials.
 */
export function UrlScrapePopover({
  courseId,
  disabled,
  onScraped,
  onScrapingChange,
}: UrlScrapePopoverProps) {
  const t = useT();
  const [isScraping, setIsScraping] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [urlPopoverOpen, setUrlPopoverOpen] = useState(false);

  const handleUrlSubmit = useCallback(async () => {
    const url = urlInput.trim();
    if (!url) return;

    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      toast.error(t("url.invalidUrl"));
      return;
    }

    setIsScraping(true);
    onScrapingChange?.(true);
    try {
      await scrapeUrl(courseId, url);
      toast.success(t("url.addSuccess"));
      setUrlInput("");
      setUrlPopoverOpen(false);
      onScraped();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error(t("url.scrapeFailed").replace("{message}", msg));
    } finally {
      setIsScraping(false);
      onScrapingChange?.(false);
    }
  }, [urlInput, courseId, onScraped, onScrapingChange, t]);

  const handleUrlKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        void handleUrlSubmit();
      }
      if (e.key === "Escape") {
        setUrlPopoverOpen(false);
      }
    },
    [handleUrlSubmit],
  );

  return (
    <Popover open={urlPopoverOpen} onOpenChange={setUrlPopoverOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="mb-0.5 text-muted-foreground hover:text-foreground"
          title={t("url.addUrl")}
          aria-label={t("url.addUrl")}
          disabled={disabled}
        >
          {isScraping ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Link className="size-4" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-80 rounded-xl border border-border/60 card-shadow p-3">
        <p className="mb-2 text-xs font-medium text-foreground">
          {t("url.addUrlToCourse")}
        </p>
        <div className="flex items-center gap-1.5">
          <input
            type="url"
            aria-label={t("url.addUrlToCourse")}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={handleUrlKeyDown}
            placeholder="https://example.com/lecture-notes"
            disabled={isScraping}
            className={cn(
              "flex-1 rounded-xl border border-border/60 bg-transparent px-2.5 py-1.5 text-sm",
              "placeholder:text-muted-foreground",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
            autoFocus
          />
          <Button
            type="button"
            size="sm"
            className="h-8 rounded-xl px-3 text-xs"
            disabled={!urlInput.trim() || isScraping}
            onClick={() => void handleUrlSubmit()}
          >
            {isScraping ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              t("url.add")
            )}
          </Button>
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          {t("url.helpText")}
        </p>
      </PopoverContent>
    </Popover>
  );
}
