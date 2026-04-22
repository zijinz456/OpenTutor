import { describe, it, expect, vi, beforeEach } from "vitest";
import * as React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { CodeExerciseBlock } from "./code-exercise-block";
import type { PyodideRunResult } from "@/lib/pyodide-runtime";

// ---------- Module mocks -----------------------------------------------------
//
// Monaco is mocked as a plain <textarea> so tests can fire `change` events
// without spinning up a real editor (which needs workers + WebGL). We mirror
// the `value`/`onChange` contract of @monaco-editor/react's Editor.
//
// `next/dynamic` is mocked to return the mocked module synchronously —
// Next's default `dynamic(() => import(...))` returns a lazy component
// which React suspends on for the first render; bypassing keeps tests
// simple and isn't what we're testing (the dynamic-import boundary is
// exercised at the module level via vi.mock).
vi.mock("@monaco-editor/react", () => {
  return {
    __esModule: true,
    default: ({
      value,
      onChange,
    }: {
      value?: string;
      onChange?: (v: string | undefined) => void;
    }) => (
      <textarea
        data-testid="monaco-editor"
        aria-label="Python code editor"
        value={value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
      />
    ),
  };
});

vi.mock("next/dynamic", () => ({
  __esModule: true,
  // Stand-in: resolve the loader eagerly and return a wrapper that forces
  // a state update when the component becomes available. Tests don't run
  // inside a <Suspense> boundary, so we can't throw promises; instead we
  // useState to flip from placeholder to the resolved component.
  default: (
    loader: () => Promise<{ default: React.ComponentType<unknown> }>,
  ) => {
    // Kick off the import immediately at module-resolution time. Because
    // `@monaco-editor/react` is vi.mocked above, this resolves in a single
    // microtask.
    const loaderPromise = loader();
    const DynamicStub = (props: Record<string, unknown>) => {
      const [Resolved, setResolved] = React.useState<
        React.ComponentType<unknown> | null
      >(null);
      React.useEffect(() => {
        let mounted = true;
        loaderPromise.then((mod) => {
          if (mounted) setResolved(() => mod.default);
        });
        return () => {
          mounted = false;
        };
      }, []);
      if (!Resolved) return null;
      return <Resolved {...props} />;
    };
    return DynamicStub;
  },
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark" }),
}));

// Pyodide runtime mock — swap `runPython` behavior per-test via `mockPython`.
// Typed as `(code: string) => Promise<PyodideRunResult>` so `mockResolvedValue`
// on the spy narrows correctly without the legacy `vi.fn<[args], ret>` form.
const runPythonSpy: ReturnType<
  typeof vi.fn<(code: string) => Promise<PyodideRunResult>>
> = vi.fn();
const getPyodideSpy = vi.fn();

vi.mock("@/lib/pyodide-runtime", () => ({
  getPyodide: () => {
    getPyodideSpy();
    return Promise.resolve({
      isReady: () => true,
      runPython: (code: string) => runPythonSpy(code),
    });
  },
}));

// ---------- Helpers ----------------------------------------------------------

function setPythonResult(result: Partial<PyodideRunResult>) {
  runPythonSpy.mockResolvedValue({
    stdout: "",
    stderr: "",
    runtime_ms: 1,
    ...result,
  });
}

async function findEditor() {
  // Because next/dynamic mock defers resolution to the next microtask,
  // wait for the textarea to appear in the first-render frame.
  return await waitFor(() =>
    screen.getByTestId("monaco-editor") as HTMLTextAreaElement,
  );
}

// ---------- Tests ------------------------------------------------------------

describe("CodeExerciseBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setPythonResult({ stdout: "hi\n" });
  });

  it("renders prompt, starter code, Run + Submit buttons", async () => {
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="Print hi"
        onSubmit={vi.fn()}
      />,
    );
    const editor = await findEditor();
    expect(editor.value).toBe("print('hi')");
    expect(screen.getByTestId("code-exercise-prompt").textContent).toBe(
      "Print hi",
    );
    expect(screen.getByTestId("code-exercise-run")).toBeInTheDocument();
    expect(screen.getByTestId("code-exercise-submit")).toBeInTheDocument();
  });

  it("Run click invokes pyodide with editor value and renders stdout", async () => {
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="Print hi"
        onSubmit={vi.fn()}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    await waitFor(() =>
      expect(runPythonSpy).toHaveBeenCalledWith("print('hi')"),
    );
    expect(
      (await screen.findByTestId("code-exercise-stdout")).textContent,
    ).toContain("hi");
  });

  it("Run with stderr renders red stderr pane, stdout absent", async () => {
    setPythonResult({
      stdout: "",
      stderr: "Traceback: SyntaxError: invalid token",
      runtime_ms: 2,
    });
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="prin 'oops'"
        questionText="x"
        onSubmit={vi.fn()}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    const stderrPane = await screen.findByTestId("code-exercise-stderr");
    expect(stderrPane.textContent).toContain("SyntaxError");
    expect(stderrPane.className).toMatch(/text-destructive/);
    expect(screen.queryByTestId("code-exercise-stdout")).toBeNull();
  });

  it("Submit without Run shows 'Run first' hint, does NOT call onSubmit", async () => {
    const onSubmit = vi.fn();
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={onSubmit}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-submit"));
    });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      screen.getByTestId("code-exercise-run-first-hint"),
    ).toBeInTheDocument();
  });

  it("Submit after Run sends the exact payload shape", async () => {
    setPythonResult({ stdout: "hi\n", stderr: "", runtime_ms: 7 });
    const onSubmit = vi.fn().mockResolvedValue({
      is_correct: true,
      explanation: "nice",
    });
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={onSubmit}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    await screen.findByTestId("code-exercise-stdout");
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-submit"));
    });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      code: "print('hi')",
      stdout: "hi\n",
      stderr: "",
      runtime_ms: 7,
    });
  });

  it("is_correct=true renders green success badge + explanation", async () => {
    setPythonResult({ stdout: "hi\n" });
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={vi.fn().mockResolvedValue({
          is_correct: true,
          explanation: "good job",
        })}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    await screen.findByTestId("code-exercise-stdout");
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-submit"));
    });
    const correct = await screen.findByTestId("code-exercise-result-correct");
    expect(correct.textContent).toContain("Correct");
    expect(correct.textContent).toContain("good job");
    expect(correct.className).toMatch(/border-success/);
  });

  it("is_correct=false renders red failure + explanation + expected output", async () => {
    setPythonResult({ stdout: "bye\n" });
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('bye')"
        questionText="x"
        expectedOutput="hi"
        onSubmit={vi.fn().mockResolvedValue({
          is_correct: false,
          explanation: "expected hi",
        })}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    await screen.findByTestId("code-exercise-stdout");
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-submit"));
    });
    const wrong = await screen.findByTestId("code-exercise-result-wrong");
    expect(wrong.textContent).toContain("Not quite");
    expect(wrong.textContent).toContain("expected hi");
    expect(wrong.textContent).toContain("hi"); // expectedOutput surfaced
    expect(wrong.className).toMatch(/border-destructive/);
  });

  it("Next button fires onAdvance when provided", async () => {
    setPythonResult({ stdout: "hi\n" });
    const onAdvance = vi.fn();
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={vi
          .fn()
          .mockResolvedValue({ is_correct: true, explanation: "yes" })}
        onAdvance={onAdvance}
      />,
    );
    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    await screen.findByTestId("code-exercise-stdout");
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-submit"));
    });
    const next = await screen.findByTestId("code-exercise-next");
    fireEvent.click(next);
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });

  it("hints section is collapsed by default and lists hints when opened", async () => {
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode=""
        questionText="x"
        hints={["think about loops", "consider range()"]}
        onSubmit={vi.fn()}
      />,
    );
    await findEditor();
    const details = screen.getByTestId(
      "code-exercise-hints",
    ) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("Hints (2)");
    // jsdom renders <details> list items in the DOM regardless of `open`;
    // the summary opens them in a real browser. Here we just verify the
    // list content is present after opening the element programmatically.
    details.open = true;
    expect(screen.getByText("think about loops")).toBeInTheDocument();
    expect(screen.getByText("consider range()")).toBeInTheDocument();
  });

  it("hints section is absent when no hints provided", async () => {
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode=""
        questionText="x"
        onSubmit={vi.fn()}
      />,
    );
    await findEditor();
    expect(screen.queryByTestId("code-exercise-hints")).toBeNull();
  });

  it("Ctrl+Enter on the outer wrapper triggers Run", async () => {
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={vi.fn()}
      />,
    );
    await findEditor();
    const root = screen.getByTestId("code-exercise-block");
    await act(async () => {
      fireEvent.keyDown(root, { key: "Enter", ctrlKey: true });
    });
    await waitFor(() => expect(runPythonSpy).toHaveBeenCalledTimes(1));
  });

  it("Ctrl+Enter inside Monaco is ignored (does NOT trigger wrapper Run)", async () => {
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={vi.fn()}
      />,
    );
    const editor = await findEditor();
    // The editor node lives inside [data-monaco-editor-root]; keyDown from
    // inside that subtree must not be captured by our handler.
    await act(async () => {
      fireEvent.keyDown(editor, { key: "Enter", ctrlKey: true });
    });
    // Allow any scheduled promise to settle.
    await new Promise((r) => setTimeout(r, 0));
    expect(runPythonSpy).not.toHaveBeenCalled();
  });

  it("Ctrl+Shift+Enter triggers Submit (uses last-run output)", async () => {
    setPythonResult({ stdout: "hi\n", stderr: "", runtime_ms: 3 });
    const onSubmit = vi
      .fn()
      .mockResolvedValue({ is_correct: true, explanation: "ok" });
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={onSubmit}
      />,
    );
    await findEditor();
    const root = screen.getByTestId("code-exercise-block");
    // Run first
    await act(async () => {
      fireEvent.keyDown(root, { key: "Enter", ctrlKey: true });
    });
    await screen.findByTestId("code-exercise-stdout");
    // Then submit via shortcut
    await act(async () => {
      fireEvent.keyDown(root, { key: "Enter", ctrlKey: true, shiftKey: true });
    });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("editing after Run shows 'code changed' stale badge", async () => {
    setPythonResult({ stdout: "hi\n" });
    render(
      <CodeExerciseBlock
        problemId="p1"
        starterCode="print('hi')"
        questionText="x"
        onSubmit={vi.fn()}
      />,
    );
    const editor = await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("code-exercise-run"));
    });
    await screen.findByTestId("code-exercise-stdout");
    await act(async () => {
      fireEvent.change(editor, { target: { value: "print('changed')" } });
    });
    expect(screen.getByTestId("code-exercise-stale")).toBeInTheDocument();
  });
});
