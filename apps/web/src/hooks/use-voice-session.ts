/**
 * WebSocket-based voice session hook.
 *
 * Manages:
 * - WebSocket connection to /api/voice/ws/{courseId}
 * - MediaRecorder for audio capture (WebM/Opus)
 * - Audio playback queue for TTS responses
 * - State machine: idle → recording → processing → playing → idle
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getStoredAccessToken } from "@/lib/auth";
import { getSharedAudioContext } from "@/lib/audio-context";

const API_WS_BASE =
  (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
    .replace(/^http/, "ws") + "/api/voice";

export type VoiceState = "idle" | "connecting" | "recording" | "processing" | "playing";

interface VoiceMessage {
  type: "transcript" | "message" | "audio" | "status" | "done" | "error";
  text?: string;
  content?: string;
  data?: string; // base64 audio
  format?: string;
  phase?: string;
  message?: string;
  metadata?: Record<string, unknown>;
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
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef(false);
  const streamRef = useRef<MediaStream | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const connectRef = useRef<(() => Promise<WebSocket>) | null>(null);

  /** Play audio from base64 queue */
  const playNextAudio = useCallback(async () => {
    if (isPlayingRef.current || playbackQueueRef.current.length === 0) return;

    isPlayingRef.current = true;
    setVoiceState("playing");

    while (playbackQueueRef.current.length > 0) {
      const b64 = playbackQueueRef.current.shift()!;
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
      } catch (e) {
        console.error("Audio playback failed:", e);
      }
    }

    isPlayingRef.current = false;
    setVoiceState("idle");
  }, []);

  /** Handle incoming server messages */
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
        // Reset text buffers for next turn
        setTranscript("");
        setAgentText("");
        break;

      case "error":
        setError(msg.message ?? "Voice error");
        setVoiceState("idle");
        break;
    }
  }, [playNextAudio]);

  /** Connect WebSocket — returns a promise that resolves when open */
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
      const url = `${API_WS_BASE}/ws/${courseId}${params.size > 0 ? `?${params.toString()}` : ""}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      // Timeout after 5 seconds — cleared on successful open
      const connectTimeout = window.setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          ws.close();
          reject(new Error("WebSocket connection timeout"));
        }
      }, 5000);

      ws.onopen = () => {
        clearTimeout(connectTimeout);
        reconnectAttemptsRef.current = 0; // Reset on successful connect
        setVoiceState("idle");
        setError(null);
        setIsConnected(true);
        // Send config
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
          // Binary or malformed — ignore
        }
      };

      ws.onerror = () => {
        clearTimeout(connectTimeout);
        setError("Voice connection failed");
        setVoiceState("idle");
        setIsConnected(false);
        reject(new Error("WebSocket connection failed"));
      };

      ws.onclose = (event) => {
        wsRef.current = null;
        setVoiceState("idle");
        setIsConnected(false);

        // Auto-reconnect with exponential backoff (max 3 attempts)
        if (!event.wasClean && reconnectAttemptsRef.current < 3) {
          const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 8000);
          reconnectAttemptsRef.current += 1;
          console.info(`Voice WS reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`);
          reconnectTimerRef.current = window.setTimeout(() => {
            void connectRef.current?.().catch(() => {
              // Reconnect failed — will retry on next close
            });
          }, delay);
        }
      };
    });
  }, [accessToken, courseId, handleServerMessage, language, speed, ttsEnabled, ttsVoice]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  /** Send recorded audio blob to WebSocket server */
  const sendAudioToServer = useCallback(async (blob: Blob) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Voice connection lost");
      setVoiceState("idle");
      return;
    }

    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    // Efficient base64 encoding — process in chunks to avoid stack overflow
    const CHUNK_SIZE = 8192;
    let binary = "";
    for (let i = 0; i < bytes.length; i += CHUNK_SIZE) {
      const chunk = bytes.subarray(i, i + CHUNK_SIZE);
      binary += String.fromCharCode(...chunk);
    }
    const base64 = btoa(binary);

    wsRef.current.send(JSON.stringify({
      type: "audio",
      data: base64,
      format: "webm",
    }));
  }, []);

  /** Start recording audio */
  const startRecording = useCallback(async () => {
    setError(null);

    // Ensure WebSocket is connected (await open event, not a fixed timeout)
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

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = () => {
        // Stop all tracks to release microphone
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;

        // Combine chunks and send to server
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

  /** Stop recording and send audio */
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
      setVoiceState("processing");
    }
  }, []);

  /** Disconnect WebSocket */
  const disconnect = useCallback(() => {
    // Cancel any pending reconnect
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptsRef.current = 3; // Prevent reconnection
    // Stop MediaRecorder and release microphone
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    setVoiceState("idle");
    setIsConnected(false);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Stop MediaRecorder and release microphone
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
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
