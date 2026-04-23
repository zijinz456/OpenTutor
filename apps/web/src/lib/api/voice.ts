/**
 * Voice transcription client — frontend adapter (Phase 8 T3).
 *
 * Backend contract: `POST /api/voice/transcribe` (multipart form).
 *   - file:     UploadFile (audio/webm, audio/mp4, audio/mpeg, audio/wav,
 *               audio/ogg — whatever MediaRecorder produces), ≤10 MiB,
 *               ≤60 s duration.
 *   - language: optional "en" | "uk" hint (query or form field); omit for
 *               Whisper auto-detect.
 *
 * Response: `VoiceTranscribeResponse` → `{text, language, duration_ms}`.
 * Errors:
 *   - 413 clip too large (>10 MiB)
 *   - 415 unsupported MIME
 *   - 429 rate-limited (>10 clips/min per user)
 *   - 502 OpenAI Whisper upstream down / retry exhausted
 *
 * We use a direct `fetch` rather than the retrying `request` helper for
 * the same reason the screenshot client does — auto-retry on a multipart
 * POST would re-upload the whole audio blob on transient 5xx and re-bill
 * the Whisper API.
 */
import {
  API_BASE,
  ApiError,
  buildSecureRequestInit,
  parseApiError,
} from "./client";

export interface VoiceTranscribeResponse {
  text: string;
  language: string | null;
  duration_ms: number | null;
}

/** POST the audio blob to the voice transcribe endpoint. */
export async function transcribeAudio(
  blob: Blob,
  language?: "en" | "uk",
): Promise<VoiceTranscribeResponse> {
  const form = new FormData();
  // MediaRecorder Blobs don't carry a filename; FastAPI's UploadFile
  // parser is happy with any field name + optional third argument.
  const ext = blob.type.includes("webm")
    ? "webm"
    : blob.type.includes("mp4")
      ? "mp4"
      : blob.type.includes("ogg")
        ? "ogg"
        : blob.type.includes("wav")
          ? "wav"
          : "bin";
  form.append("file", blob, `voice.${ext}`);
  if (language) {
    form.append("language", language);
  }

  const res = await fetch(`${API_BASE}/voice/transcribe`, {
    ...buildSecureRequestInit({
      method: "POST",
      includeJsonContentType: false,
      body: form,
    }),
  });

  if (!res.ok) {
    throw await parseApiError(res);
  }
  return (await res.json()) as VoiceTranscribeResponse;
}

export { ApiError };
