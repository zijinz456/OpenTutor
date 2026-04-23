"use client";

/**
 * <VoiceInput> — Phase 8 T3.
 *
 * Click 🎤 → browser captures webm/opus via MediaRecorder → stop → POST
 * to `/api/voice/transcribe` → emit `onTranscribed(text)` for parent to
 * insert into textarea.
 *
 * ADHD-proofing:
 *   - Hard 60-s cap with visible countdown (`0:15 / 1:00`).
 *   - Window blur / visibilitychange auto-stops the recorder so a
 *     forgotten stop doesn't burn a minute of silent ambient audio.
 *   - Privacy copy inline: audio sent to Whisper, nothing persisted.
 *
 * All dependencies are stdlib/lucide-react — no external audio libs, the
 * waveform pulse is a single CSS keyframe.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, Mic, Square } from "lucide-react";
import { ApiError, transcribeAudio } from "@/lib/api/voice";

export interface VoiceInputProps {
  onTranscribed: (text: string) => void;
  /** Whisper language hint. Omit for auto-detect. */
  language?: "en" | "uk";
  /** Hard cap on a single clip (default 60 s). */
  maxDurationSec?: number;
  /** Disable the button (e.g. parent textarea is read-only). */
  disabled?: boolean;
}

type Phase =
  | "idle"
  | "recording"
  | "stopping"
  | "transcribing"
  | "error";

interface ErrorState {
  detail: string;
  hint?: string;
}

/** Map ApiError → ADHD-friendly `{detail, hint}`. */
function apiErrorToState(err: ApiError): ErrorState {
  switch (err.status) {
    case 413:
      return {
        detail: "Clip too long.",
        hint: "Max 60 s or 10 MiB — record a shorter chunk.",
      };
    case 415:
      return {
        detail: "Unsupported audio format.",
        hint: "Try a different browser — webm/opus expected.",
      };
    case 429:
      return {
        detail: "Too many clips — wait 60 s.",
        hint: "Max 10 voice clips per minute.",
      };
    case 502:
      return {
        detail: "Voice service down.",
        hint: "Typing still works.",
      };
    default:
      return {
        detail: err.detail ?? err.message ?? "Transcription failed.",
        hint: "Type it instead.",
      };
  }
}

/** Return the best MediaRecorder MIME supported by this browser. */
function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  for (const m of candidates) {
    // isTypeSupported may not exist in older test shims.
    if (typeof MediaRecorder.isTypeSupported === "function") {
      if (MediaRecorder.isTypeSupported(m)) return m;
    }
  }
  return "audio/webm";
}

/** Format seconds as `m:ss`. */
function fmtTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.max(0, sec - m * 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function VoiceInput({
  onTranscribed,
  language,
  maxDurationSec = 60,
  disabled = false,
}: VoiceInputProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState<number>(0);
  const [error, setError] = useState<ErrorState | null>(null);

  // Refs for the recorder + stream so cleanup doesn't race with state.
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoStopRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Hard-teardown of any active recording/stream — safe to call in any phase. */
  const teardown = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    if (autoStopRef.current) {
      clearTimeout(autoStopRef.current);
      autoStopRef.current = null;
    }
    const stream = streamRef.current;
    if (stream) {
      for (const track of stream.getTracks()) {
        try {
          track.stop();
        } catch {
          // track already stopped — harmless.
        }
      }
      streamRef.current = null;
    }
    recorderRef.current = null;
  }, []);

  // Unmount cleanup — critical so a component dropped mid-record doesn't
  // leak the mic indicator in the browser tab.
  useEffect(() => {
    return () => teardown();
  }, [teardown]);

  /** Collect → POST → emit. Runs in the `onstop` handler of MediaRecorder. */
  const uploadRecording = useCallback(
    async (mimeType: string) => {
      setPhase("transcribing");
      const blob = new Blob(chunksRef.current, { type: mimeType });
      chunksRef.current = [];
      try {
        const res = await transcribeAudio(blob, language);
        onTranscribed(res.text);
        setPhase("idle");
        setElapsed(0);
      } catch (err) {
        if (err instanceof ApiError) {
          setError(apiErrorToState(err));
        } else if (err instanceof Error) {
          setError({
            detail: err.message || "Transcription failed.",
            hint: "Type it instead.",
          });
        } else {
          setError({
            detail: "Transcription failed.",
            hint: "Type it instead.",
          });
        }
        setPhase("error");
      }
    },
    [language, onTranscribed],
  );

  /** Begin MediaRecorder — wires chunks, countdown, auto-stop. */
  const startRecording = useCallback(async () => {
    if (phase !== "idle" && phase !== "error") return;
    setError(null);
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      setError({
        detail: "Microphone not supported in this browser.",
        hint: "Type it instead.",
      });
      setPhase("error");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        // Stream is stopped here so the browser mic indicator clears the
        // moment the user hits stop, not after the (slower) upload.
        const stream = streamRef.current;
        if (stream) {
          for (const track of stream.getTracks()) {
            try {
              track.stop();
            } catch {
              // harmless
            }
          }
          streamRef.current = null;
        }
        if (tickRef.current) {
          clearInterval(tickRef.current);
          tickRef.current = null;
        }
        if (autoStopRef.current) {
          clearTimeout(autoStopRef.current);
          autoStopRef.current = null;
        }
        void uploadRecording(mimeType);
      };
      recorder.start();
      setPhase("recording");
      setElapsed(0);
      // Countdown tick — pure UI, not load-bearing for stop logic.
      tickRef.current = setInterval(() => {
        setElapsed((e) => e + 1);
      }, 1000);
      // Hard stop at maxDurationSec — doesn't depend on the tick.
      autoStopRef.current = setTimeout(() => {
        const r = recorderRef.current;
        if (r && r.state === "recording") {
          setPhase("stopping");
          r.stop();
        }
      }, maxDurationSec * 1000);
    } catch (err) {
      // Permission denied, no device, etc.
      const msg =
        err instanceof Error && err.name === "NotAllowedError"
          ? "Mic blocked."
          : "Couldn't start recording.";
      setError({
        detail: msg,
        hint: "Click the 🔒 in the address bar to allow mic access.",
      });
      setPhase("error");
      teardown();
    }
  }, [maxDurationSec, phase, teardown, uploadRecording]);

  /** Manual stop — user hit the stop button. */
  const stopRecording = useCallback(() => {
    const r = recorderRef.current;
    if (r && r.state === "recording") {
      setPhase("stopping");
      r.stop();
    }
  }, []);

  // Auto-stop on tab/window blur or visibility hidden — ADHD save: user
  // tabs out mid-thought, we don't want 45 min of silent audio piling up.
  useEffect(() => {
    if (phase !== "recording") return;
    const onBlur = () => {
      const r = recorderRef.current;
      if (r && r.state === "recording") {
        setPhase("stopping");
        r.stop();
      }
    };
    const onVis = () => {
      if (document.visibilityState === "hidden") onBlur();
    };
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [phase]);

  const remaining = Math.max(0, maxDurationSec - elapsed);

  return (
    <div
      className="flex items-center gap-2"
      data-testid="voice-input"
      data-phase={phase}
    >
      {(phase === "idle" || phase === "error") && (
        <button
          type="button"
          data-testid="voice-input-start"
          onClick={() => void startRecording()}
          disabled={disabled}
          title="Record voice"
          aria-label="Record voice"
          className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:border-brand hover:text-foreground disabled:opacity-50"
        >
          <Mic className="size-4" />
        </button>
      )}

      {(phase === "recording" || phase === "stopping") && (
        <button
          type="button"
          data-testid="voice-input-stop"
          onClick={stopRecording}
          disabled={phase === "stopping"}
          title="Stop recording"
          aria-label="Stop recording"
          className="inline-flex size-9 items-center justify-center rounded-lg border border-red-400/70 bg-red-50 text-red-700 animate-pulse disabled:opacity-60"
        >
          <Square className="size-3 fill-current" />
        </button>
      )}

      {phase === "transcribing" && (
        <span
          data-testid="voice-input-transcribing"
          className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground"
        >
          <Loader2 className="size-4 animate-spin" />
        </span>
      )}

      {phase === "recording" && (
        <span
          data-testid="voice-input-countdown"
          className="text-xs font-mono tabular-nums text-muted-foreground"
        >
          {fmtTime(elapsed)} / {fmtTime(maxDurationSec)}
          <span className="sr-only">
            {" "}
            ({remaining} seconds remaining)
          </span>
        </span>
      )}

      {phase === "error" && error && (
        <span
          role="alert"
          data-testid="voice-input-error"
          className="inline-flex items-center gap-1 text-xs text-red-700"
        >
          <AlertCircle className="size-3.5" />
          <span data-testid="voice-input-error-detail">{error.detail}</span>
          {error.hint && (
            <span
              className="text-red-900/70"
              data-testid="voice-input-error-hint"
            >
              {error.hint}
            </span>
          )}
        </span>
      )}
    </div>
  );
}

export default VoiceInput;
