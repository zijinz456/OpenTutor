"use client";

import { useEffect, useState } from "react";
import { ChevronDown, MoonStar, Snowflake, TimerReset } from "lucide-react";
import { getFreezeStatus } from "@/lib/api/freeze";
import { cn } from "@/lib/utils";
import { useBadDayStore } from "@/store/bad-day";
import { usePanicStore } from "@/store/panic";
import { usePomodoroStore } from "@/store/pomodoro";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";

function formatRemaining(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function ToggleRow({
  label,
  active,
  onToggle,
  testId,
}: {
  label: string;
  active: boolean;
  onToggle: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      data-testid={testId}
      className="flex w-full items-center justify-between gap-3 rounded-xl border border-border/70 bg-background/60 px-3 py-3 text-left transition-colors hover:bg-muted/70"
    >
      <span className="text-sm font-medium text-foreground">{label}</span>
      <span
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors",
          active ? "bg-brand" : "bg-muted",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform",
            active ? "translate-x-5" : "translate-x-0.5",
          )}
        />
      </span>
    </button>
  );
}

export function TodayToolsPopover() {
  const quietMode = usePanicStore((state) => state.enabled);
  const toggleQuietMode = usePanicStore((state) => state.toggle);
  const easyMode = useBadDayStore((state) => state.isActiveToday());
  const toggleEasyMode = useBadDayStore((state) => state.toggle);

  const pomodoroEnabled = usePomodoroStore((state) => state.enabled);
  const phase = usePomodoroStore((state) => state.phase);
  const phaseEndsAt = usePomodoroStore((state) => state.phaseEndsAt);
  const setPomodoroEnabled = usePomodoroStore((state) => state.setEnabled);
  const startFocus = usePomodoroStore((state) => state.startFocus);
  const advancePhase = usePomodoroStore((state) => state.advancePhase);
  const pauseSession = usePomodoroStore((state) => state.pauseSession);

  const [open, setOpen] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const [quotaRemaining, setQuotaRemaining] = useState(2);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void getFreezeStatus()
      .then((status) => {
        if (!cancelled) {
          setQuotaRemaining(status.quota_remaining);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (phase === "idle") {
      setRemaining(0);
      return;
    }
    const updateRemaining = () => {
      setRemaining(Math.max(0, phaseEndsAt - Date.now()));
    };
    updateRemaining();
    const intervalId = window.setInterval(updateRemaining, 1000);
    return () => window.clearInterval(intervalId);
  }, [phase, phaseEndsAt]);

  const pomodoroLabel =
    phase === "idle"
      ? "Pomodoro"
      : phase === "focus"
        ? `${formatRemaining(remaining)} focus`
        : `Break ${formatRemaining(remaining)}`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="today-tools-trigger"
          className="inline-flex h-9 items-center gap-2 rounded-full border border-border/80 bg-card/80 px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted/80"
        >
          Today tools
          <ChevronDown className="size-4 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[22rem] border-border/80 bg-card/95 p-4 backdrop-blur"
      >
        <PopoverHeader className="mb-4">
          <PopoverTitle>Today tools</PopoverTitle>
          <PopoverDescription>
            Keep the dashboard lighter. No guilt necessary.
          </PopoverDescription>
        </PopoverHeader>

        <div className="space-y-3">
          <div className="grid gap-3">
            <ToggleRow
              label="Quiet mode"
              active={quietMode}
              onToggle={toggleQuietMode}
              testId="today-tools-quiet-toggle"
            />
            <ToggleRow
              label="Easy mode"
              active={easyMode}
              onToggle={toggleEasyMode}
              testId="today-tools-easy-toggle"
            />
          </div>

          <section
            data-testid="today-tools-pomodoro"
            className="rounded-xl border border-border/70 bg-background/60 p-3"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <TimerReset className="size-4 text-brand" />
              <span>{pomodoroLabel}</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {!pomodoroEnabled ? (
                <button
                  type="button"
                  onClick={() => setPomodoroEnabled(true)}
                  className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted/70"
                >
                  Turn on
                </button>
              ) : phase === "idle" ? (
                <button
                  type="button"
                  onClick={startFocus}
                  className="rounded-full bg-brand px-3 py-1 text-xs font-medium text-brand-foreground transition-opacity hover:opacity-90"
                >
                  Start focus
                </button>
              ) : phase === "focus" ? (
                <button
                  type="button"
                  onClick={pauseSession}
                  className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted/70"
                >
                  Pause
                </button>
              ) : (
                <button
                  type="button"
                  onClick={advancePhase}
                  className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted/70"
                >
                  Skip break
                </button>
              )}
            </div>
          </section>

          <section
            data-testid="today-tools-freezes"
            className="flex items-center gap-2 rounded-xl border border-border/70 bg-background/60 px-3 py-3 text-sm text-foreground"
          >
            <Snowflake className="size-4 text-track-english" />
            <span>{quotaRemaining} freezes left</span>
          </section>

          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <MoonStar className="size-3.5" />
            <span>Quiet mode hides the noisy stuff.</span>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
