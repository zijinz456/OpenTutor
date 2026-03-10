"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Mic, MicOff, AudioLines, Loader2 } from "lucide-react";
import type { VoiceState } from "@/hooks/use-voice-session";

interface VoiceSession {
  voiceState: VoiceState;
  transcript: string | null;
  error: string | null;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
}

interface VoiceButtonProps {
  voice: VoiceSession;
  disabled: boolean;
}

function getVoiceTitle(state: VoiceState): string {
  if (state === "recording") return "Stop recording";
  if (state === "processing") return "Processing...";
  return "Voice input";
}

function VoiceIcon({ state }: { state: VoiceState }) {
  if (state === "recording") return <MicOff className="size-4" />;
  if (state === "processing") return <Loader2 className="size-4 animate-spin" />;
  if (state === "playing") return <AudioLines className="size-4" />;
  return <Mic className="size-4" />;
}

/**
 * Voice recording toggle button with a status indicator strip below.
 */
export function VoiceButton({ voice, disabled }: VoiceButtonProps) {
  const isClickDisabled =
    disabled ||
    voice.voiceState === "processing" ||
    voice.voiceState === "playing";

  function handleClick(): void {
    if (voice.voiceState === "recording") {
      voice.stopRecording();
    } else {
      void voice.startRecording();
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      className={cn(
        "mb-0.5 text-muted-foreground hover:text-foreground",
        voice.voiceState === "recording" && "text-red-500 animate-pulse",
        voice.voiceState === "processing" && "text-amber-500",
        voice.voiceState === "playing" && "text-green-500",
      )}
      title={getVoiceTitle(voice.voiceState)}
      aria-label={voice.voiceState === "recording" ? "Stop recording" : "Start voice recording"}
      aria-pressed={voice.voiceState === "recording"}
      disabled={isClickDisabled}
      onClick={handleClick}
    >
      <VoiceIcon state={voice.voiceState} />
    </Button>
  );
}

/**
 * Displays the current voice session status: recording, processing, or playing.
 */
export function VoiceStatusIndicator({ voice }: { voice: VoiceSession }) {
  if (voice.voiceState === "idle") return null;

  return (
    <div role="status" aria-live="polite" className="mt-1.5 flex items-center gap-2 rounded-xl bg-muted/20 px-2 py-1 text-xs text-muted-foreground animate-fade-in">
      {voice.voiceState === "recording" && (
        <>
          <span className="inline-block size-2 rounded-full bg-red-500 animate-pulse" />
          <span>Recording... click mic to stop</span>
        </>
      )}
      {voice.voiceState === "processing" && (
        <>
          <Loader2 className="size-3 animate-spin" />
          <span>
            {voice.transcript
              ? `"${voice.transcript}"`
              : "Processing audio..."}
          </span>
        </>
      )}
      {voice.voiceState === "playing" && (
        <>
          <AudioLines className="size-3 text-green-500" />
          <span>Playing response...</span>
        </>
      )}
      {voice.error && (
        <span className="text-destructive">{voice.error}</span>
      )}
    </div>
  );
}
