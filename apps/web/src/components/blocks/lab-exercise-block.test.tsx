import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import {
  LabExerciseBlock,
  type LabExerciseSubmitPayload,
  type LabExerciseSubmitResult,
} from "./lab-exercise-block";

// ---------- Helpers ---------------------------------------------------------

type SubmitFn = (
  payload: LabExerciseSubmitPayload,
) => Promise<LabExerciseSubmitResult>;

// `vi.fn()` in the tests below types as `Mock<Procedure | Constructable>`
// which doesn't automatically satisfy a typed arrow signature. We coerce via
// `as unknown as SubmitFn` at the boundary so individual tests can keep
// using ergonomic `vi.fn().mockResolvedValue(...)` without per-call casts.
function renderBlock(overrides: {
  onSubmit?: unknown;
  onAdvance?: (() => void) | ReturnType<typeof vi.fn>;
  targetUrl?: string;
  hints?: string[];
  category?: string;
  difficulty?: "easy" | "medium" | "hard";
} = {}) {
  const onSubmit: SubmitFn =
    (overrides.onSubmit as SubmitFn | undefined) ??
    ((vi.fn().mockResolvedValue({
      is_correct: true,
      explanation: "solved",
    }) as unknown) as SubmitFn);
  const onAdvance = overrides.onAdvance as (() => void) | undefined;
  const { hints, category, difficulty } = overrides;
  render(
    <LabExerciseBlock
      problemId="lab1"
      questionText="Find a reflected XSS in Juice Shop's search."
      targetUrl={overrides.targetUrl ?? "http://localhost:3100/#/search"}
      category={category}
      difficulty={difficulty}
      hints={hints}
      onSubmit={onSubmit}
      onAdvance={onAdvance}
    />,
  );
  return { onSubmit, onAdvance };
}

async function fillRequired() {
  // Fill payload + flag so the Submit button is enabled.
  fireEvent.change(screen.getByTestId("lab-exercise-payload"), {
    target: { value: "<script>alert(1)</script>" },
  });
  fireEvent.change(screen.getByTestId("lab-exercise-flag"), {
    target: { value: "Alert fired on search results page" },
  });
}

// ---------- Tests -----------------------------------------------------------

describe("LabExerciseBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders task, Open Lab button, and all 3 input fields", () => {
    renderBlock();
    expect(screen.getByTestId("lab-exercise-prompt").textContent).toContain(
      "reflected XSS",
    );
    expect(screen.getByTestId("lab-exercise-open-lab")).toBeInTheDocument();
    expect(screen.getByTestId("lab-exercise-payload")).toBeInTheDocument();
    expect(screen.getByTestId("lab-exercise-flag")).toBeInTheDocument();
    expect(screen.getByTestId("lab-exercise-screenshot")).toBeInTheDocument();
  });

  it("Open Lab anchor has correct href and opens in new tab with rel=noopener noreferrer", () => {
    renderBlock({ targetUrl: "http://localhost:3100/#/search" });
    const link = screen.getByTestId("lab-exercise-open-lab") as HTMLAnchorElement;
    expect(link.href).toBe("http://localhost:3100/#/search");
    expect(link.getAttribute("target")).toBe("_blank");
    // rel must contain BOTH noopener and noreferrer to block window.opener leaks.
    const rel = link.getAttribute("rel") ?? "";
    expect(rel).toContain("noopener");
    expect(rel).toContain("noreferrer");
  });

  it("safety banner is always visible (not a prop toggle)", () => {
    renderBlock();
    const banner = screen.getByTestId("lab-exercise-safety-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(/local sandbox/i);
  });

  it("Submit is disabled when required fields are empty", () => {
    renderBlock();
    const submit = screen.getByTestId("lab-exercise-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("Submit is disabled when only payload is filled", () => {
    renderBlock();
    fireEvent.change(screen.getByTestId("lab-exercise-payload"), {
      target: { value: "payload" },
    });
    const submit = screen.getByTestId("lab-exercise-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("Submit becomes enabled once both required fields are filled", async () => {
    renderBlock();
    await fillRequired();
    const submit = screen.getByTestId("lab-exercise-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });

  it("screenshot_url with non-localhost scheme shows inline error and disables Submit", async () => {
    renderBlock();
    await fillRequired();
    fireEvent.change(screen.getByTestId("lab-exercise-screenshot"), {
      target: { value: "https://evil.com/pwn.png" },
    });
    expect(
      screen.getByTestId("lab-exercise-screenshot-error"),
    ).toBeInTheDocument();
    const submit = screen.getByTestId("lab-exercise-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("screenshot_url matching lookalike hostname is rejected", async () => {
    // Backend regex anchors `(/|$)` — "http://localhost:8080.evil.com"
    // must not pass client-side either.
    renderBlock();
    await fillRequired();
    fireEvent.change(screen.getByTestId("lab-exercise-screenshot"), {
      target: { value: "http://localhost:8080.evil.com/shot.png" },
    });
    expect(
      screen.getByTestId("lab-exercise-screenshot-error"),
    ).toBeInTheDocument();
  });

  it("empty screenshot_url is allowed (field is optional)", async () => {
    renderBlock();
    await fillRequired();
    // Do NOT touch the screenshot field. Submit should still enable.
    const submit = screen.getByTestId("lab-exercise-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    expect(
      screen.queryByTestId("lab-exercise-screenshot-error"),
    ).toBeNull();
  });

  it("valid localhost screenshot_url passes validation", async () => {
    renderBlock();
    await fillRequired();
    fireEvent.change(screen.getByTestId("lab-exercise-screenshot"), {
      target: { value: "http://localhost:3100/screenshots/xss.png" },
    });
    expect(
      screen.queryByTestId("lab-exercise-screenshot-error"),
    ).toBeNull();
    const submit = screen.getByTestId("lab-exercise-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });

  it("Submit calls onSubmit with the exact payload shape (screenshot omitted when empty)", async () => {
    const onSubmit = vi
      .fn()
      .mockResolvedValue({ is_correct: true, explanation: "ok" });
    renderBlock({ onSubmit });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      payload_used: "<script>alert(1)</script>",
      flag_or_evidence: "Alert fired on search results page",
      screenshot_url: undefined,
    });
  });

  it("Submit forwards screenshot_url when provided", async () => {
    const onSubmit = vi
      .fn()
      .mockResolvedValue({ is_correct: true });
    renderBlock({ onSubmit });
    await fillRequired();
    fireEvent.change(screen.getByTestId("lab-exercise-screenshot"), {
      target: { value: "http://localhost:3100/screenshots/xss.png" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      payload_used: "<script>alert(1)</script>",
      flag_or_evidence: "Alert fired on search results page",
      screenshot_url: "http://localhost:3100/screenshots/xss.png",
    });
  });

  it("trims whitespace from payload, flag, and screenshot before submit", async () => {
    const onSubmit = vi.fn().mockResolvedValue({ is_correct: true });
    renderBlock({ onSubmit });
    fireEvent.change(screen.getByTestId("lab-exercise-payload"), {
      target: { value: "  <script>alert(1)</script>  " },
    });
    fireEvent.change(screen.getByTestId("lab-exercise-flag"), {
      target: { value: "  Alert fired  " },
    });
    fireEvent.change(screen.getByTestId("lab-exercise-screenshot"), {
      target: { value: "  http://localhost:3100/s.png  " },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith({
      payload_used: "<script>alert(1)</script>",
      flag_or_evidence: "Alert fired",
      screenshot_url: "http://localhost:3100/s.png",
    });
  });

  it("renders green success pane with explanation on is_correct=true", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: true,
        explanation: "Good proof — XSS reflected.",
      }),
    });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    const correct = await screen.findByTestId("lab-exercise-result-correct");
    expect(correct.textContent).toContain("Solved");
    expect(correct.textContent).toContain("Good proof");
    expect(correct.className).toMatch(/border-success/);
  });

  it("renders red failure pane on is_correct=false", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: false,
        explanation: "Flag mismatch.",
      }),
    });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    const wrong = await screen.findByTestId("lab-exercise-result-wrong");
    expect(wrong.textContent).toContain("Not yet");
    expect(wrong.textContent).toContain("Flag mismatch");
    expect(wrong.className).toMatch(/border-destructive/);
  });

  it("renders confidence badge when grader returns numeric confidence", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({
        is_correct: true,
        explanation: "passes",
        confidence: 0.72,
      }),
    });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    const badge = await screen.findByTestId("lab-exercise-confidence");
    expect(badge.textContent).toMatch(/72/);
  });

  it("does not render confidence badge when field is omitted", async () => {
    renderBlock({
      onSubmit: vi.fn().mockResolvedValue({ is_correct: true }),
    });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    await screen.findByTestId("lab-exercise-result-correct");
    expect(screen.queryByTestId("lab-exercise-confidence")).toBeNull();
  });

  it("category and difficulty badges render when provided", () => {
    renderBlock({ category: "XSS", difficulty: "medium" });
    expect(screen.getByTestId("lab-exercise-category").textContent).toBe("XSS");
    expect(screen.getByTestId("lab-exercise-difficulty").textContent).toBe(
      "medium",
    );
  });

  it("Next button fires onAdvance when provided and result is present", async () => {
    const onAdvance = vi.fn();
    renderBlock({
      onAdvance,
      onSubmit: vi
        .fn()
        .mockResolvedValue({ is_correct: true, explanation: "ok" }),
    });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    const next = await screen.findByTestId("lab-exercise-next");
    fireEvent.click(next);
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });

  it("hints are collapsed by default and list the provided items", () => {
    renderBlock({ hints: ["try ?q=<svg>", "look at network tab"] });
    const details = screen.getByTestId(
      "lab-exercise-hints",
    ) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.textContent).toContain("Hints (2)");
    details.open = true;
    expect(screen.getByText("try ?q=<svg>")).toBeInTheDocument();
    expect(screen.getByText("look at network tab")).toBeInTheDocument();
  });

  it("hints section is absent when no hints provided", () => {
    renderBlock();
    expect(screen.queryByTestId("lab-exercise-hints")).toBeNull();
  });

  it("inputs are disabled while submitting and after a verdict is rendered", async () => {
    let resolveSubmit: (v: { is_correct: boolean }) => void = () => {};
    const onSubmit = vi.fn(
      () =>
        new Promise<{ is_correct: boolean }>((res) => {
          resolveSubmit = res;
        }),
    );
    renderBlock({ onSubmit });
    await fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("lab-exercise-submit"));
    });
    // While pending
    const payload = screen.getByTestId("lab-exercise-payload") as HTMLTextAreaElement;
    expect(payload.disabled).toBe(true);
    await act(async () => {
      resolveSubmit({ is_correct: true });
    });
    await screen.findByTestId("lab-exercise-result-correct");
    // After resolution — still locked so user can't edit and re-submit
    expect(payload.disabled).toBe(true);
  });

  it("renders target URL as small muted text under the button", () => {
    renderBlock({ targetUrl: "http://localhost:3100/#/search" });
    expect(screen.getByTestId("lab-exercise-target-url").textContent).toBe(
      "http://localhost:3100/#/search",
    );
  });
});
