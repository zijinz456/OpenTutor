import { describe, it, expect, vi, beforeEach } from "vitest";
import * as React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ApplyBlock } from "./apply-block";
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
      explanation: "Nice rewrite.",
    }) as unknown) as SubmitFn);

  render(
    <ApplyBlock
      problemId="apply-1"
      questionText={
        overrides.questionText ??
        "Rewrite this function using asyncio."
      }
      starterCode={
        overrides.starterCode ??
        "def fetch_all(urls):\n    return [fetch(url) for url in urls]\n"
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

describe("ApplyBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders prompt, editor wrapper, and submit button", async () => {
    renderBlock();

    expect(screen.getByText(/rewrite this function using asyncio/i)).toBeInTheDocument();
    expect(screen.getByTestId("apply-block-editor")).toBeInTheDocument();
    expect(await findEditor()).toBeInTheDocument();
    expect(screen.getByTestId("apply-block-submit")).toBeInTheDocument();
  });

  it("submit click calls onSubmit with the editor contents", async () => {
    const { onSubmit } = renderBlock();
    const editor = await findEditor();

    fireEvent.change(editor, {
      target: { value: "async def fetch_all(urls):\n    return await gather(urls)\n" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("apply-block-submit"));
    });

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      "async def fetch_all(urls):\n    return await gather(urls)\n",
    );
  });

  it("shows the correct verdict banner on a successful response", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: true,
        correct_answer: null,
        explanation: "Nice rewrite.",
      }),
    });

    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("apply-block-submit"));
    });

    const verdict = await screen.findByTestId("apply-block-result-correct");
    expect(verdict.textContent).toContain("Correct");
    expect(verdict.textContent).toContain("Nice rewrite");
  });

  it("shows an inline error message when submit fails", async () => {
    renderBlock({
      onSubmit: vi.fn().mockRejectedValue(new Error("network down")),
    });

    await findEditor();
    await act(async () => {
      fireEvent.click(screen.getByTestId("apply-block-submit"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("apply-block-submit-error")).toHaveTextContent(
        /network down/i,
      ),
    );
  });
});
