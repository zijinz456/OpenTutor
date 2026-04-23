import { describe, it, expect, vi, beforeEach } from "vitest";
import * as React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { RebuildBlock } from "./rebuild-block";
import type { AnswerResult } from "@/lib/api";

vi.mock("@monaco-editor/react", () => {
  return {
    __esModule: true,
    default: ({
      value,
      defaultValue,
      onChange,
    }: {
      value?: string;
      defaultValue?: string;
      onChange?: (v: string | undefined) => void;
    }) => (
      <textarea
        data-testid="monaco-editor"
        aria-label="Python code editor"
        defaultValue={defaultValue ?? value ?? ""}
        onChange={(e) => onChange?.(e.target.value)}
      />
    ),
  };
});

vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: (
    loader: () => Promise<{ default: React.ComponentType<unknown> }>,
  ) => {
    const loaderPromise = loader();
    const DynamicStub = (props: Record<string, unknown>) => {
      const [Resolved, setResolved] = React.useState<React.ComponentType<unknown> | null>(null);
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

type SubmitFn = (answer: string) => Promise<AnswerResult>;

function renderBlock(
  overrides: {
    onSubmit?: unknown;
    starterCode?: string;
    questionText?: string;
  } = {},
) {
  const onSubmit: SubmitFn =
    (overrides.onSubmit as SubmitFn | undefined) ??
    ((vi.fn().mockResolvedValue({
      is_correct: true,
      correct_answer: null,
      explanation: "Recovered correctly.",
    }) as unknown) as SubmitFn);

  render(
    <RebuildBlock
      problemId="rebuild-1"
      questionText={overrides.questionText ?? "Fill every # TODO gap."}
      starterCode={
        overrides.starterCode ??
        "def add(a, b):\n    # TODO\n"
      }
      onSubmit={onSubmit}
    />,
  );

  return { onSubmit };
}

async function findEditor() {
  return await waitFor(() =>
    screen.getByTestId("monaco-editor") as HTMLTextAreaElement,
  );
}

describe("RebuildBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders prompt, editor wrapper, and submit button", async () => {
    renderBlock();

    expect(screen.getByText(/fill every # todo gap/i)).toBeInTheDocument();
    expect(screen.getByTestId("rebuild-block-editor")).toBeInTheDocument();
    expect(await findEditor()).toBeInTheDocument();
    expect(screen.getByTestId("rebuild-block-submit")).toBeInTheDocument();
  });

  it("submit click calls onSubmit with the rebuilt code", async () => {
    const { onSubmit } = renderBlock();
    const editor = await findEditor();

    fireEvent.change(editor, {
      target: { value: "def add(a, b):\n    return a + b\n" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("rebuild-block-submit"));
    });

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith("def add(a, b):\n    return a + b\n");
  });

  it("shows the correct verdict banner on a successful response", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: true,
        correct_answer: null,
        explanation: "Recovered correctly.",
      }),
    });

    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("rebuild-block-submit"));
    });

    const verdict = await screen.findByTestId("rebuild-block-result-correct");
    expect(verdict.textContent).toContain("Correct");
    expect(verdict.textContent).toContain("Recovered correctly");
  });

  it("shows an inline error message when submit fails", async () => {
    renderBlock({
      onSubmit: vi.fn().mockRejectedValue(new Error("network down")),
    });

    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("rebuild-block-submit"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("rebuild-block-submit-error")).toHaveTextContent(
        /network down/i,
      ),
    );
  });
});
