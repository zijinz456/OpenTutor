/**
 * Shared AudioContext singleton.
 *
 * Browsers limit the number of AudioContext instances.  This module provides
 * a single lazily-created instance that can be shared across voice playback,
 * podcast decoding, and any other audio processing.
 */

let _ctx: AudioContext | null = null;

export function getSharedAudioContext(): AudioContext {
  if (!_ctx || _ctx.state === "closed") {
    _ctx = new AudioContext();
  }
  // Resume if suspended (browser autoplay policy)
  if (_ctx.state === "suspended") {
    void _ctx.resume();
  }
  return _ctx;
}

export function closeSharedAudioContext(): void {
  if (_ctx) {
    void _ctx.close();
    _ctx = null;
  }
}
