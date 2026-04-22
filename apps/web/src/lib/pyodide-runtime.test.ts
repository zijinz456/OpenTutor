import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  getPyodide,
  __resetPyodideForTests,
  __PYODIDE_CDN_BASE__,
  __PYODIDE_LOADER_SRC__,
} from "./pyodide-runtime";
import type { PyodideApi } from "@/types/pyodide";

// ----- shared test double ----------------------------------------------------

interface MockPyodideOptions {
  throwOnRun?: boolean;
  customThrow?: unknown;
  pythonOutput?: string;
  pythonErrorOutput?: string;
}

interface MockPyodideState {
  runCalls: string[];
  loaderCallCount: { count: number };
  stdoutBatched?: (output: string) => void;
  stderrBatched?: (output: string) => void;
}

function installMockPyodide(
  options: MockPyodideOptions = {},
): MockPyodideState {
  const state: MockPyodideState = {
    runCalls: [],
    loaderCallCount: { count: 0 },
  };

  const api: PyodideApi = {
    runPythonAsync: vi.fn(async (code: string) => {
      state.runCalls.push(code);
      if (options.pythonOutput !== undefined) {
        state.stdoutBatched?.(options.pythonOutput);
      }
      if (options.pythonErrorOutput !== undefined) {
        state.stderrBatched?.(options.pythonErrorOutput);
      }
      if (options.throwOnRun) {
        throw options.customThrow ?? new Error("boom");
      }
      return undefined;
    }),
    setStdout: vi.fn(({ batched }) => {
      state.stdoutBatched = batched;
    }),
    setStderr: vi.fn(({ batched }) => {
      state.stderrBatched = batched;
    }),
  };

  // Simulate how the real CDN loader behaves: appending the script element
  // with src=pyodide.js populates `window.loadPyodide`. We fake that by
  // patching `document.createElement` for this test run.
  const originalCreateElement = document.createElement.bind(document);
  const patchedCreate = (tag: string, opts?: ElementCreationOptions) => {
    const el = originalCreateElement(tag, opts);
    if (tag.toLowerCase() === "script") {
      // The real loader appends script.src = URL and fires `load` once the
      // browser has fetched it. We intercept the append via the `src`
      // setter: as soon as the runtime assigns the src, schedule a
      // synchronous-microtask `load` event so `addEventListener('load')`
      // fires.
      const script = el as HTMLScriptElement;
      const srcDescriptor = Object.getOwnPropertyDescriptor(
        HTMLScriptElement.prototype,
        "src",
      );
      if (srcDescriptor?.set) {
        Object.defineProperty(script, "src", {
          configurable: true,
          get() {
            return srcDescriptor.get?.call(script);
          },
          set(value: string) {
            srcDescriptor.set!.call(script, value);
            // When the production code appends to head, expose the loader.
            queueMicrotask(() => {
              state.loaderCallCount.count += 1;
              (window as Window).loadPyodide = vi.fn(async () => api);
              script.dispatchEvent(new Event("load"));
            });
          },
        });
      }
    }
    return el;
  };
  vi.spyOn(document, "createElement").mockImplementation(
    patchedCreate as typeof document.createElement,
  );

  return state;
}

// ----- tests -----------------------------------------------------------------

describe("pyodide-runtime", () => {
  beforeEach(() => {
    __resetPyodideForTests();
    // Clean up any previous loader script markers between tests.
    document
      .querySelectorAll("script[data-pyodide-loader]")
      .forEach((el) => el.remove());
    delete (window as { loadPyodide?: unknown }).loadPyodide;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is a singleton — two callers share one init", async () => {
    const state = installMockPyodide();
    const p1 = getPyodide();
    const p2 = getPyodide();
    // Same promise reference — single-flight, not just same result.
    expect(p1).toBe(p2);
    const r1 = await p1;
    const r2 = await p2;
    expect(r1).toBe(r2);
    // Loader fired exactly once.
    expect(state.loaderCallCount.count).toBe(1);
  });

  it("captures stdout from print()", async () => {
    installMockPyodide({ pythonOutput: "hi\n" });
    const runtime = await getPyodide();
    const result = await runtime.runPython("print('hi')");
    expect(result.stdout).toContain("hi");
    expect(result.stderr).toBe("");
  });

  it("captures stderr from warnings", async () => {
    installMockPyodide({ pythonErrorOutput: "DeprecationWarning: old\n" });
    const runtime = await getPyodide();
    const result = await runtime.runPython("import warnings; warnings.warn('old')");
    expect(result.stderr).toContain("DeprecationWarning");
    expect(result.stdout).toBe("");
  });

  it("reports a non-negative, sub-second runtime_ms on a trivial run", async () => {
    installMockPyodide();
    const runtime = await getPyodide();
    const result = await runtime.runPython("x = 1 + 1");
    expect(result.runtime_ms).toBeGreaterThanOrEqual(0);
    expect(result.runtime_ms).toBeLessThan(1000);
  });

  it("never throws on a Python error — places message in stderr", async () => {
    installMockPyodide({
      throwOnRun: true,
      customThrow: new Error("SyntaxError: invalid token"),
    });
    const runtime = await getPyodide();
    // MUST NOT throw.
    const result = await runtime.runPython("prin 'oops'");
    expect(result.stderr).toContain("SyntaxError");
    expect(result.stdout).toBe("");
  });

  it("falls back to String() for non-Error throws", async () => {
    installMockPyodide({ throwOnRun: true, customThrow: "raw string" });
    const runtime = await getPyodide();
    const result = await runtime.runPython("???");
    expect(result.stderr).toContain("raw string");
  });

  it("buffers reset between runs — second run does not leak first run's output", async () => {
    // Custom mock: emit different stdout on each `runPythonAsync` call so we
    // can verify the second run's result does not include the first run's
    // output. Can't use `installMockPyodide` since it only supports a single
    // fixed `pythonOutput`.
    const nextOutputs = ["first\n", "second\n"];
    let currentStdout: ((output: string) => void) | undefined;
    const api: PyodideApi = {
      runPythonAsync: vi.fn(async () => {
        const chunk = nextOutputs.shift() ?? "";
        currentStdout?.(chunk);
        return undefined;
      }),
      setStdout: vi.fn(({ batched }) => {
        currentStdout = batched;
      }),
      setStderr: vi.fn(),
    };
    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(
      (tag: string, opts?: ElementCreationOptions) => {
        const el = originalCreate(tag, opts);
        if (tag.toLowerCase() === "script") {
          const script = el as HTMLScriptElement;
          const srcDescriptor = Object.getOwnPropertyDescriptor(
            HTMLScriptElement.prototype,
            "src",
          );
          if (srcDescriptor?.set) {
            Object.defineProperty(script, "src", {
              configurable: true,
              get() {
                return srcDescriptor.get?.call(script);
              },
              set(value: string) {
                srcDescriptor.set!.call(script, value);
                queueMicrotask(() => {
                  (window as Window).loadPyodide = vi.fn(async () => api);
                  script.dispatchEvent(new Event("load"));
                });
              },
            });
          }
        }
        return el;
      },
    );

    const runtime = await getPyodide();
    const r1 = await runtime.runPython("print('first')");
    expect(r1.stdout).toContain("first");

    const r2 = await runtime.runPython("print('second')");
    expect(r2.stdout).not.toContain("first");
    expect(r2.stdout).toContain("second");
  });

  it("injects the pinned CDN script URL — no unpinned 'latest'", async () => {
    installMockPyodide();
    await getPyodide();
    const script = document.querySelector<HTMLScriptElement>(
      "script[data-pyodide-loader]",
    );
    expect(script).not.toBeNull();
    expect(script!.src).toBe(__PYODIDE_LOADER_SRC__);
    expect(__PYODIDE_LOADER_SRC__).toContain(__PYODIDE_CDN_BASE__);
    expect(__PYODIDE_LOADER_SRC__).not.toContain("latest");
    // Must be a pinned semver segment.
    expect(__PYODIDE_LOADER_SRC__).toMatch(/\/v\d+\.\d+\.\d+\//);
  });

  it("rejects in non-browser environment with a clear message", async () => {
    // Simulate SSR: temporarily hide `window`. We can't truly `delete window`
    // under jsdom, so stub the runtime's view via a Proxy-ish shim: the
    // implementation only checks `typeof window === 'undefined'`, so we have
    // to patch `globalThis.window`.
    const savedWindow = globalThis.window;
    // @ts-expect-error — deliberately removing window for the SSR branch
    delete globalThis.window;

    __resetPyodideForTests();
    try {
      await expect(getPyodide()).rejects.toThrow(/client-only|window/i);
    } finally {
      // Restore window so subsequent tests keep working.
      globalThis.window = savedWindow;
    }
  });

  it("clears singleton on init failure so a retry can succeed", async () => {
    // First attempt: patch createElement to fire `error` instead of `load`.
    const originalCreate = document.createElement.bind(document);
    const failingSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation((tag: string, opts?: ElementCreationOptions) => {
        const el = originalCreate(tag, opts);
        if (tag.toLowerCase() === "script") {
          queueMicrotask(() => el.dispatchEvent(new Event("error")));
        }
        return el;
      });

    await expect(getPyodide()).rejects.toThrow(/Failed to load/);
    failingSpy.mockRestore();

    // Second attempt: happy path — singleton should have been cleared so we
    // actually retry instead of returning the cached rejected promise.
    document
      .querySelectorAll("script[data-pyodide-loader]")
      .forEach((el) => el.remove());
    installMockPyodide();
    const runtime = await getPyodide();
    expect(runtime.isReady()).toBe(true);
  });
});
