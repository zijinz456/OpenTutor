/**
 * Minimal ambient types for the Pyodide CDN loader.
 *
 * Pyodide is delivered via CDN (jsdelivr) per Code Runner Phase 11 Q4=A:
 * the runtime script sets `window.loadPyodide` globally. We only type the
 * slice of the API we call from `src/lib/pyodide-runtime.ts`; everything else
 * stays `unknown` so accidental misuse surfaces as a type error.
 */

export interface PyodideApi {
  runPythonAsync: (code: string) => Promise<unknown>;
  setStdout: (options: { batched: (output: string) => void }) => void;
  setStderr: (options: { batched: (output: string) => void }) => void;
}

export interface LoadPyodideOptions {
  indexURL: string;
}

declare global {
  interface Window {
    loadPyodide?: (options: LoadPyodideOptions) => Promise<PyodideApi>;
  }
}

export {};
