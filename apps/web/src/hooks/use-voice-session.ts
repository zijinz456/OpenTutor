/**
 * WebSocket-based voice session hook.
 *
 * Manages:
 * - WebSocket connection to /api/voice/ws/{courseId}
 * - MediaRecorder for audio capture (WebM/Opus)
 * - Audio playback queue for TTS responses
 * - State machine: idle -> recording -> processing -> playing -> idle
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getStoredAccessToken } from "@/lib/auth";
import { getSharedAudioContext } from "@/lib/audio-context";
import { API_BASE } from "@/lib/api/client";
import { trackApiFailure } from "@/lib/error-telemetry";

const API_WS_BASE =
  API_BASE.replace(/^http/, "ws").replace(/\/api$/, "") + "/api/voice";

export type VoiceState = "idle" | "connecting" | "recording" | "processing" | "playing";

interface VoiceMessage {
  type: "transcript" | "message" | "audio" | "status" | "done" | "error";
  text?: string;
  content?: string;
  data?: string;
  phase?: string;
  message?: string;
}

interface UseVoiceSessionOptions {
  ttsVoice?: string;
  ttsEnabled?: boolean;
  language?: string;
  speed?: number;
  accessToken?: string;
}

export function useVoiceSession(courseId: string, options?: UseVoiceSessionOptions) {
  const accessToken = options?.accessToken;
  const ttsVoice = options?.ttsVoice ?? "alloy";
  const ttsEnabled = options?.ttsEnabled ?? true;
  const language = options?.language ?? "auto";
  const speed = options?.speed ?? 1.0;

  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [transcript, setTranscript] = useState("");
  const [agentText, setAgentText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const connectRef = useRef<(() => Promise<WebSocket>) | null>(null);
  const unmountedRef = useRef(false);

  const playNextAudio = useCallback(async () => {
    if (unmountedRef.current) return;
    if (isPlayingRef.current || playbackQueueRef.current.length === 0) return;

    isPlayingRef.current = true;
    setVoiceState("playing");

    while (playbackQueueRef.current.length > 0) {
      const b64 = playbackQueueRef.current.shift();
      if (!b64) continue;

      try {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        if (!audioContextRef.current) {
          audioContextRef.current = getSharedAudioContext();
        }
        const audioBuffer = await audioContextRef.current.decodeAudioData(
          bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
        );
        const source = audioContextRef.current.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContextRef.current.destination);
        await new Promise<void>((resolve) => {
          source.onended = () => resolve();
          source.start();
        });
      } catch (playbackError) {
        console.error("Audio playback failed:", playbackError);
      }
    }

    isPlayingRef.current = false;
    setVoiceState("idle");
  }, []);

  const handleServerMessage = useCallback((msg: VoiceMessage) => {
    switch (msg.type) {
      case "transcript":
        setTranscript(msg.text ?? "");
        setVoiceState("processing");
        break;
      case "message":
        setAgentText((prev) => prev + (msg.content ?? ""));
        break;
      case "audio":
        if (msg.data) {
          playbackQueueRef.current.push(msg.data);
          void playNextAudio();
        }
        break;
      case "status":
        if (msg.phase === "speaking") {
          setVoiceState("playing");
        }
        break;
      case "done":
        if (!isPlayingRef.current) {
          setVoiceState("idle");
        }
        setTranscript("");
        setAgentText("");
        break;
      case "error":
        setError(msg.message ?? "Voice error");
        setVoiceState("idle");
        break;
    }
  }, [playNextAudio]);

  const connect = useCallback((): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        resolve(wsRef.current);
        return;
      }

      setVoiceState("connecting");
      const params = new URLSearchParams();
      const resolvedAccessToken = accessToken ?? getStoredAccessToken();
      if (resolvedAccessToken) {
        params.set("token", resolvedAccessToken);
      }
      const wsUrl = `${API_WS_BASE}/ws/${courseId}${params.size > 0 ? `?${params.toString()}` : ""}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      const connectTimeout = window.setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          ws.close();
          reject(new Error("WebSocket connection timeout"));
        }
      }, 5000);

      ws.onopen = () => {
        clearTimeout(connectTimeout);
        reconnectAttemptsRef.current = 0;
        setVoiceState("idle");
        setError(null);
        setIsConnected(true);
        ws.send(JSON.stringify({
          type: "config",
          tts_voice: ttsVoice,
          tts_enabled: ttsEnabled,
          language,
          speed,
        }));
        resolve(ws);
      };

      ws.onmessage = (event) => {
        try {
          const msg: VoiceMessage = JSON.parse(event.data);
          handleServerMessage(msg);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onerror = () => {
        clearTimeout(connectTimeout);
        setError("Voice connection failed");
        setVoiceState("idle");
        setIsConnected(false);
        trackApiFailure("voice", new Error("websocket_error"), {
          endpoint: `/voice/ws/${courseId}`,
          courseId,
          meta: { phase: "connect" },
        });
        reject(new Error("WebSocket connection failed"));
      };

      ws.onclose = (event) => {
        wsRef.current = null;
        setVoiceState("idle");
        setIsConnected(false);

        if (!event.wasClean && reconnectAttemptsRef.current < 3) {
          const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 8000);
          reconnectAttemptsRef.current += 1;
          reconnectTimerRef.current = window.setTimeout(() => {
            void connectRef.current?.().catch(() => {
              // no-op: retry handled by close lifecycle
            });
          }, delay);
        }
      };
    });
  }, [accessToken, courseId, handleServerMessage, language, speed, ttsEnabled, ttsVoice]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const sendAudioToServer = useCallback(async (blob: Blob) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Voice connection lost");
      setVoiceState("idle");
      return;
    }

    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    const chunkSize = 8192;
    let binary = "";
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode(...chunk);
    }
    const base64 = btoa(binary);

    wsRef.current.send(JSON.stringify({
      type: "audio",
      data: base64,
      format: "webm",
    }));
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);

    try {
      await connect();
    } catch {
      setError("Voice connection not ready");
      return;
    }

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Voice connection not ready");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      audioChunksRef.current = [];

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        void sendAudioToServer(blob);
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start();
      setVoiceState("recording");
    } catch {
      setError("Microphone access denied");
      setVoiceState("idle");
    }
  }, [connect, sendAudioToServer]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
      setVoiceState("processing");
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptsRef.current = 3;

    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    wsRef.current?.close();
    wsRef.current = null;
    setVoiceState("idle");
    setIsConnected(false);
  }, []);

  useEffect(() => {
    return () => {
      unmountedRef.current = true;
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }
      wsRef.current?.close();
      audioContextRef.current?.close();
    };
  }, []);

  return {
    voiceState,
    transcript,
    agentText,
    error,
    isConnected,
    startRecording,
    stopRecording,
    connect,
    disconnect,
  };
}
