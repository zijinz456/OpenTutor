/**
 * Pyodide runtime — lazy singleton loader.
 *
 * Code Runner Phase 11 T2 (plan: plan/code_runner_phase11.md).
 *
 * Contract:
 *   - `getPyodide()` returns a cached Promise. First call injects the CDN
 *     loader script and initializes Pyodide; subsequent calls await the same
 *     promise (single-flight).
 *   - `runPython(code)` ALWAYS resolves. Syntax / runtime errors are placed
 *     into the `stderr` field of the return value — they never throw. The
 *     <CodeExerciseBlock> component (T3) depends on this contract to render
 *     red output without try/catch.
 *   - SSR-safe to import: module-level code never touches `window`. Calling
 *     `getPyodide()` in a non-browser context rejects with a clear message.
 *
 * Delivery:
 *   - Pinned to Pyodide v0.27.0 (stable; shipped with CPython 3.12.7 + the
 *     `setStdout`/`setStderr` batched-callback API we rely on).
 *   - CDN: jsdelivr. Chosen per Q4=A for the first ship. Self-hosting under
 *     `public/pyodide/` is parked for Phase 11.5 once bundle size matters.
 *   - The CSP in `next.config.ts` whitelists `https://cdn.jsdelivr.net` on
 *     both `script-src` (for the loader) and `connect-src` (the loader
 *     `fetch()`s the WASM + stdlib tarball from the same origin).
 *
 * NOT pinned via npm on purpose: bundling Pyodide through Turbopack/webpack
 * has historically been fragile under Next 16. CDN keeps the build boring.
 */

import type { PyodideApi } from "@/types/pyodide";

const PYODIDE_VERSION = "0.27.0";
const PYODIDE_CDN_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PYODIDE_LOADER_SRC = `${PYODIDE_CDN_BASE}pyodide.js`;
const LOADER_SCRIPT_MARKER = "data-pyodide-loader";

export interface PyodideRunResult {
  stdout: string;
  stderr: string;
  runtime_ms: number;
}

export interface PyodideRuntime {
  runPython(code: string): Promise<PyodideRunResult>;
  isReady(): boolean;
}

// Module-scope singleton cache. Not exported — external callers always go
// through `getPyodide()` so we keep single-flight guarantees.
let _pyodidePromise: Promise<PyodideRuntime> | null = null;

/**
 * Inject the Pyodide CDN loader script into <head>. Idempotent — a second
 * call with the script already present resolves immediately.
 *
 * Returns a promise that resolves once `window.loadPyodide` is defined.
 */
function injectLoaderScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined" || typeof document === "undefined") {
      reject(new Error("Pyodide loader requires a browser environment"));
      return;
    }

    // Fast path: loader already ran (e.g. another caller kicked it).
    if (typeof window.loadPyodide === "function") {
      resolve();
      return;
    }

    const existing = document.querySelector<HTMLScriptElement>(
      `script[${LOADER_SCRIPT_MARKER}]`,
    );
    if (existing) {
      // Another invocation already appended the script; wait for it.
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("Pyodide loader script failed to load")),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.src = PYODIDE_LOADER_SRC;
    script.async = true;
    script.setAttribute(LOADER_SCRIPT_MARKER, "true");
    script.addEventListener("load", () => resolve(), { once: true });
    script.addEventListener(
      "error",
      () => reject(new Error(`Failed to load ${PYODIDE_LOADER_SRC}`)),
      { once: true },
    );
    document.head.appendChild(script);
  });
}

/**
 * Wrap a raw Pyodide API handle in the `PyodideRuntime` contract used by
 * the rest of the app. Captures stdout/stderr into per-call buffers via
 * the `setStdout({batched})` / `setStderr({batched})` hooks.
 */
function wrapRuntime(api: PyodideApi): PyodideRuntime {
  let stdoutBuffer: string[] = [];
  let stderrBuffer: string[] = [];

  api.setStdout({
    batched: (output: string) => {
      stdoutBuffer.push(output);
    },
  });
  api.setStderr({
    batched: (output: string) => {
      stderrBuffer.push(output);
    },
  });

  return {
    isReady: () => true,
    async runPython(code: string): Promise<PyodideRunResult> {
      stdoutBuffer = [];
      stderrBuffer = [];
      const started =
        typeof performance !== "undefined" ? performance.now() : Date.now();
      try {
        await api.runPythonAsync(code);
      } catch (err) {
        // Syntax errors, NameErrors, runtime exceptions — Pyodide typically
        // already emits the traceback to stderr. Append the error toString
        // defensively so the user always sees something actionable.
        const message =
          err instanceof Error ? err.message : String(err ?? "unknown error");
        stderrBuffer.push(message);
      }
      const ended =
        typeof performance !== "undefined" ? performance.now() : Date.now();
      return {
        stdout: stdoutBuffer.join(""),
        stderr: stderrBuffer.join(""),
        runtime_ms: Math.max(0, ended - started),
      };
    },
  };
}

async function initializePyodide(): Promise<PyodideRuntime> {
  if (typeof window === "undefined") {
    throw new Error("Pyodide is client-only; getPyodide() requires window");
  }
  await injectLoaderScript();
  const loader = window.loadPyodide;
  if (typeof loader !== "function") {
    throw new Error("window.loadPyodide is missing after script load");
  }
  const api = await loader({ indexURL: PYODIDE_CDN_BASE });
  return wrapRuntime(api);
}

/**
 * Retrieve the lazy Pyodide runtime singleton.
 *
 * Safe to call many times — the first call triggers initialization; all
 * subsequent calls await the same promise. On failure the cached promise is
 * cleared so the next call can retry (e.g. after a transient network error).
 */
export function getPyodide(): Promise<PyodideRuntime> {
  if (_pyodidePromise) {
    return _pyodidePromise;
  }
  _pyodidePromise = initializePyodide().catch((err) => {
    // Reset on failure so a subsequent call can retry the load.
    _pyodidePromise = null;
    throw err;
  });
  return _pyodidePromise;
}

/**
 * Test-only reset. Not exported through the package's public surface, but
 * usable from vitest via the `@/lib/pyodide-runtime` import.
 */
export function __resetPyodideForTests(): void {
  _pyodidePromise = null;
}

export const __PYODIDE_CDN_BASE__ = PYODIDE_CDN_BASE;
export const __PYODIDE_LOADER_SRC__ = PYODIDE_LOADER_SRC;
