import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QuizView } from "./quiz-view";
import { toast } from "sonner";

vi.mock("@/lib/api", async () => {
  const problems = [
    {
      id: "p1",
      question: "What color is the sky?",
      question_type: "multiple_choice",
      options: { a: "Red", b: "Blue", c: "Green" },
      difficulty_layer: 1,
      problem_metadata: { core_concept: "Atmosphere" },
    },
    {
      id: "p2",
      question: "2 + 2 = ?",
      question_type: "multiple_choice",
      options: { a: "3", b: "4", c: "5" },
      difficulty_layer: 1,
      problem_metadata: {},
    },
  ];
  return {
    listProblems: vi.fn().mockResolvedValue(problems),
    extractQuiz: vi.fn().mockResolvedValue({ problems_created: 5 }),
    submitAnswer: vi.fn().mockResolvedValue({
      is_correct: true,
      correct_answer: "b",
      explanation: "Blue is correct.",
      prerequisite_gaps: [],
    }),
  };
});

// Code Runner (§34.5 Phase 11 T4): stub <CodeExerciseBlock> so dispatch
// tests don't pull in Monaco/Pyodide (exercised exhaustively in T3 tests).
// The stub exposes the props we care about asserting + a test-only button
// that invokes `onSubmit` with a fixed payload, letting us verify the
// adapter's envelope shape against the real /quiz/submit client.
vi.mock("@/components/blocks/code-exercise-block", () => {
  function CodeExerciseBlock(props: {
    problemId: string;
    starterCode: string;
    questionText: string;
    expectedOutput?: string;
    hints?: string[];
    onSubmit: (p: {
      code: string;
      stdout: string;
      stderr: string;
      runtime_ms: number;
    }) => Promise<{ is_correct: boolean; explanation?: string }>;
    onAdvance?: () => void;
  }) {
    return (
      <div data-testid="code-exercise-block-stub">
        <span data-testid="ceb-problem-id">{props.problemId}</span>
        <span data-testid="ceb-starter">{props.starterCode}</span>
        <span data-testid="ceb-question">{props.questionText}</span>
        <span data-testid="ceb-expected">{props.expectedOutput ?? ""}</span>
        <span data-testid="ceb-hints">
          {(props.hints ?? []).join("|")}
        </span>
        <button
          data-testid="ceb-trigger-submit"
          onClick={() =>
            void props.onSubmit({
              code: "print(2)",
              stdout: "2",
              stderr: "",
              runtime_ms: 50,
            })
          }
        >
          trigger-submit
        </button>
        {props.onAdvance ? (
          <button
            data-testid="ceb-trigger-advance"
            onClick={() => props.onAdvance?.()}
          >
            trigger-advance
          </button>
        ) : null}
      </div>
    );
  }
  return { CodeExerciseBlock };
});

// Hacking Labs (§34.6 Phase 12 T4): stub <LabExerciseBlock> — same pattern as
// the code-exercise stub above. We want to exercise the dispatch branch +
// adapter envelope WITHOUT rendering the real textareas / banner / validator
// (those live in lab-exercise-block.test.tsx).
vi.mock("@/components/blocks/lab-exercise-block", () => {
  function LabExerciseBlock(props: {
    problemId: string;
    questionText: string;
    targetUrl: string;
    category?: string;
    difficulty?: "easy" | "medium" | "hard";
    hints?: string[];
    onSubmit: (p: {
      payload_used: string;
      flag_or_evidence: string;
      screenshot_url?: string;
    }) => Promise<{
      is_correct: boolean;
      explanation?: string;
      confidence?: number;
    }>;
    onAdvance?: () => void;
  }) {
    return (
      <div data-testid="lab-exercise-block-stub">
        <span data-testid="leb-problem-id">{props.problemId}</span>
        <span data-testid="leb-target-url">{props.targetUrl}</span>
        <span data-testid="leb-category">{props.category ?? ""}</span>
        <span data-testid="leb-difficulty">{props.difficulty ?? ""}</span>
        <span data-testid="leb-question">{props.questionText}</span>
        <span data-testid="leb-hints">{(props.hints ?? []).join("|")}</span>
        <button
          data-testid="leb-trigger-submit"
          onClick={() =>
            void props.onSubmit({
              payload_used: "<script>alert(1)</script>",
              flag_or_evidence: "Alert fired",
              screenshot_url: "http://localhost:3100/s.png",
            })
          }
        >
          trigger-submit
        </button>
        {props.onAdvance ? (
          <button
            data-testid="leb-trigger-advance"
            onClick={() => props.onAdvance?.()}
          >
            trigger-advance
          </button>
        ) : null}
      </div>
    );
  }
  return { LabExerciseBlock };
});

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("sonner", () => ({
  toast: {
    warning: vi.fn(),
  },
}));

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ sectionRefreshKey: { practice: 0 }, spaceLayout: { mode: "self_paced", blocks: [] } }),
    {
      getState: () => ({
        sectionRefreshKey: { practice: 0 },
        spaceLayout: { mode: "self_paced", blocks: [] },
        addBlock: vi.fn(),
        reorderBlocks: vi.fn(),
      }),
    },
  ),
}));

vi.mock("@/lib/block-system/feature-unlock", () => ({
  updateUnlockContext: vi.fn(),
  getUnlockContext: () => ({ practiceAttempts: 0, hasWrongAnswer: false }),
}));

vi.mock("@/components/shared/ai-feature-blocked", () => ({
  AiFeatureBlocked: () => <div data-testid="ai-blocked" />,
}));

vi.mock("./use-quiz-persistence", () => ({
  useQuizPersistence: () => ({ save: vi.fn(), load: vi.fn().mockReturnValue(null), clear: vi.fn() }),
}));

describe("QuizView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", async () => {
    render(<QuizView courseId="test" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  it("renders quiz question after loading", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => {
      expect(screen.getByText("What color is the sky?")).toBeInTheDocument();
    });
  });

  it("has role=form with aria-label", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByRole("form", { name: "quiz.ariaLabel" })).toBeInTheDocument();
  });

  it("has role=radiogroup for answer options", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByRole("radiogroup", { name: "quiz.answerOptions" })).toBeInTheDocument();
  });

  it("renders answer options as radio buttons", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
  });

  it("selects option and submits answer on click", async () => {
    const { submitAnswer } = await import("@/lib/api");
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    const optionB = screen.getByTestId("quiz-option-b");
    fireEvent.click(optionB);

    await waitFor(() => {
      expect(submitAnswer).toHaveBeenCalledWith("p1", "b", expect.any(Number));
    });
  });

  it("shows explanation after answering", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    fireEvent.click(screen.getByTestId("quiz-option-b"));

    await waitFor(() => {
      expect(screen.getByText(/Blue is correct/)).toBeInTheDocument();
    });
  });

  it("shows fallback feedback when explanation details are missing", async () => {
    const { submitAnswer } = await import("@/lib/api");
    vi.mocked(submitAnswer).mockResolvedValueOnce({
      is_correct: false,
      correct_answer: null,
      explanation: null,
      prerequisite_gaps: [],
    });

    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    fireEvent.click(screen.getByTestId("quiz-option-b"));

    await waitFor(() => {
      expect(screen.getByText("quiz.answerRecorded")).toBeInTheDocument();
      expect(screen.getByText("quiz.feedbackUnavailable")).toBeInTheDocument();
    });
    expect(toast.warning).toHaveBeenCalledWith("quiz.feedbackWarning");
  });

  it("navigates to next question", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));

    const nextBtn = screen.getByText("quiz.next");
    fireEvent.click(nextBtn);

    await waitFor(() => {
      expect(screen.getByText("2 + 2 = ?")).toBeInTheDocument();
    });
  });

  it("disables previous button on first question", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByText("quiz.prev")).toBeDisabled();
  });

  it("shows core concept badge", async () => {
    render(<QuizView courseId="test" />);
    await waitFor(() => screen.getByText("What color is the sky?"));
    expect(screen.getByText("Atmosphere")).toBeInTheDocument();
  });
});

// Code Runner (§34.5 Phase 11 T4) — `code_exercise` dispatch branch.
// Verifies that:
//   1. The CodeExerciseBlock replaces MC radios when question_type is
//      "code_exercise".
//   2. Starter code + hints are read from `problem_metadata`.
//   3. `expected_output` from metadata is NOT leaked to the block prop.
//   4. The onSubmit adapter stringifies the payload into /quiz/submit's
//      user_answer envelope.
//   5. Missing `starter_code` falls back to an empty string.
describe("QuizView — code_exercise dispatch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function renderWithProblems(
    problems: unknown[],
    submitResult: {
      is_correct: boolean;
      correct_answer: string | null;
      explanation: string | null;
    } = {
      is_correct: true,
      correct_answer: null,
      explanation: "Nice — runs.",
    },
  ) {
    const api = await import("@/lib/api");
    // Use mockResolvedValue (not Once) because QuizView's fetchData effect
    // may re-fire if dependencies re-identity (e.g. mocked hook returning
    // fresh closures). We want this problem set to win for the whole test.
    vi.mocked(api.listProblems).mockResolvedValue(
      problems as Awaited<ReturnType<typeof api.listProblems>>,
    );
    vi.mocked(api.submitAnswer).mockResolvedValue({
      ...submitResult,
      prerequisite_gaps: [],
    });
    render(<QuizView courseId="test" />);
    return api;
  }

  it("renders <CodeExerciseBlock> instead of MC radios for code_exercise", async () => {
    await renderWithProblems([
      {
        id: "ce1",
        question: "Print the number 2",
        question_type: "code_exercise",
        options: null,
        difficulty_layer: 1,
        problem_metadata: {
          starter_code: "# write your code here\n",
          expected_output: "2",
          stdout_normalizer: "rstrip",
          hints: ["use print()", "int literal 2"],
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("code-exercise-block-stub")).toBeInTheDocument(),
    );
    // MC radios must NOT appear
    expect(screen.queryByRole("radiogroup")).toBeNull();
    // Props surfaced correctly
    expect(screen.getByTestId("ceb-problem-id").textContent).toBe("ce1");
    expect(screen.getByTestId("ceb-starter").textContent).toBe(
      "# write your code here\n",
    );
    expect(screen.getByTestId("ceb-question").textContent).toBe(
      "Print the number 2",
    );
    expect(screen.getByTestId("ceb-hints").textContent).toBe(
      "use print()|int literal 2",
    );
    // SECURITY: expected_output must NOT be forwarded to the block. The
    // stub renders the expectedOutput prop verbatim — empty string proves
    // the parent never passed it.
    expect(screen.getByTestId("ceb-expected").textContent).toBe("");
  });

  it("adapter POSTs JSON-stringified payload as user_answer", async () => {
    const api = await renderWithProblems([
      {
        id: "ce1",
        question: "q",
        question_type: "code_exercise",
        options: null,
        difficulty_layer: 1,
        problem_metadata: { starter_code: "" },
      },
    ]);
    const trigger = await screen.findByTestId("ceb-trigger-submit");
    fireEvent.click(trigger);
    // The stub's onClick fires void props.onSubmit(...) → our
    // handleCodeExerciseSubmit → submitAnswer(). submitAnswer is a vi.fn
    // that records the call synchronously; the downstream setScore/
    // setAnsweredMap run on the next microtask. A single Promise.resolve
    // flush is enough to see the recorded call.
    await Promise.resolve();
    expect(api.submitAnswer).toHaveBeenCalledWith(
      "ce1",
      JSON.stringify({
        code: "print(2)",
        stdout: "2",
        stderr: "",
        runtime_ms: 50,
      }),
      expect.any(Number),
    );
  });

  it("falls back to empty starter_code when metadata omits it", async () => {
    await renderWithProblems([
      {
        id: "ce2",
        question: "q",
        question_type: "code_exercise",
        options: null,
        difficulty_layer: 1,
        problem_metadata: { hints: ["only hints"] }, // no starter_code
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("code-exercise-block-stub")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ceb-starter").textContent).toBe("");
    expect(screen.getByTestId("ceb-hints").textContent).toBe("only hints");
  });

  it("ignores non-string entries in metadata.hints", async () => {
    await renderWithProblems([
      {
        id: "ce3",
        question: "q",
        question_type: "code_exercise",
        options: null,
        difficulty_layer: 1,
        problem_metadata: {
          starter_code: "pass",
          hints: ["good", 42, null, "also good"], // dirty shape
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("code-exercise-block-stub")).toBeInTheDocument(),
    );
    // Only string hints survive the narrow
    expect(screen.getByTestId("ceb-hints").textContent).toBe("good|also good");
  });

  it("onAdvance is only wired when there IS a next problem", async () => {
    await renderWithProblems([
      {
        id: "only",
        question: "q",
        question_type: "code_exercise",
        options: null,
        difficulty_layer: 1,
        problem_metadata: { starter_code: "" },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("code-exercise-block-stub")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("ceb-trigger-advance")).toBeNull();
  });
});

// Hacking Labs (§34.6 Phase 12 T4) — `lab_exercise` dispatch branch.
// Verifies:
//   1. LabExerciseBlock renders (not MC, not CodeExerciseBlock) when
//      question_type === "lab_exercise".
//   2. target_url, category, difficulty, hints flow from problem_metadata.
//   3. verification_rubric / expected_artifact_type are NOT forwarded.
//   4. adapter stringifies the proof into /quiz/submit's user_answer envelope.
//   5. Missing target_url → fall-back renders an error, NOT the block.
describe("QuizView — lab_exercise dispatch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function renderWithProblems(
    problems: unknown[],
    submitResult: {
      is_correct: boolean;
      correct_answer: string | null;
      explanation: string | null;
    } = {
      is_correct: true,
      correct_answer: null,
      explanation: "Nice proof.",
    },
  ) {
    const api = await import("@/lib/api");
    vi.mocked(api.listProblems).mockResolvedValue(
      problems as Awaited<ReturnType<typeof api.listProblems>>,
    );
    vi.mocked(api.submitAnswer).mockResolvedValue({
      ...submitResult,
      prerequisite_gaps: [],
    });
    render(<QuizView courseId="test" />);
    return api;
  }

  it("renders <LabExerciseBlock> instead of MC radios for lab_exercise", async () => {
    await renderWithProblems([
      {
        id: "lab1",
        question: "Find a reflected XSS in search.",
        question_type: "lab_exercise",
        options: null,
        difficulty_layer: 2,
        problem_metadata: {
          target_url: "http://localhost:3100/#/search",
          category: "XSS",
          difficulty: "medium",
          hints: ["try ?q=<svg>", "use onerror"],
          // These must NOT leak to the block (SECURITY)
          verification_rubric: "payload must contain <script> and flag 'XSS'",
          expected_artifact_type: "alert_dialog",
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("lab-exercise-block-stub")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByTestId("code-exercise-block-stub")).toBeNull();
    expect(screen.getByTestId("leb-problem-id").textContent).toBe("lab1");
    expect(screen.getByTestId("leb-target-url").textContent).toBe(
      "http://localhost:3100/#/search",
    );
    expect(screen.getByTestId("leb-category").textContent).toBe("XSS");
    expect(screen.getByTestId("leb-difficulty").textContent).toBe("medium");
    expect(screen.getByTestId("leb-question").textContent).toBe(
      "Find a reflected XSS in search.",
    );
    expect(screen.getByTestId("leb-hints").textContent).toBe(
      "try ?q=<svg>|use onerror",
    );
  });

  it("adapter POSTs JSON-stringified proof payload as user_answer", async () => {
    const api = await renderWithProblems([
      {
        id: "lab1",
        question: "q",
        question_type: "lab_exercise",
        options: null,
        difficulty_layer: 2,
        problem_metadata: {
          target_url: "http://localhost:3100/#/search",
        },
      },
    ]);
    const trigger = await screen.findByTestId("leb-trigger-submit");
    fireEvent.click(trigger);
    await Promise.resolve();
    expect(api.submitAnswer).toHaveBeenCalledWith(
      "lab1",
      JSON.stringify({
        payload_used: "<script>alert(1)</script>",
        flag_or_evidence: "Alert fired",
        screenshot_url: "http://localhost:3100/s.png",
      }),
      expect.any(Number),
    );
  });

  it("falls back with alert when target_url is missing from metadata", async () => {
    await renderWithProblems([
      {
        id: "broken",
        question: "q",
        question_type: "lab_exercise",
        options: null,
        difficulty_layer: 2,
        problem_metadata: { category: "XSS" }, // no target_url
      },
    ]);
    // Block must NOT render; a visible error should take its place.
    await waitFor(() =>
      expect(
        screen.getByTestId("lab-exercise-missing-target"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("lab-exercise-block-stub")).toBeNull();
  });

  it("ignores non-literal difficulty values from metadata", async () => {
    await renderWithProblems([
      {
        id: "lab2",
        question: "q",
        question_type: "lab_exercise",
        options: null,
        difficulty_layer: 2,
        problem_metadata: {
          target_url: "http://localhost:3100/#/search",
          difficulty: "extreme", // not in easy|medium|hard
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("lab-exercise-block-stub")).toBeInTheDocument(),
    );
    // Unknown difficulty narrows to undefined → stub renders empty string.
    expect(screen.getByTestId("leb-difficulty").textContent).toBe("");
  });

  it("filters non-string entries from metadata.hints", async () => {
    await renderWithProblems([
      {
        id: "lab3",
        question: "q",
        question_type: "lab_exercise",
        options: null,
        difficulty_layer: 2,
        problem_metadata: {
          target_url: "http://localhost:3100/#/search",
          hints: ["good", 42, null, "also good"],
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("lab-exercise-block-stub")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("leb-hints").textContent).toBe("good|also good");
  });

  it("onAdvance is wired only when a next problem exists", async () => {
    await renderWithProblems([
      {
        id: "solo",
        question: "q",
        question_type: "lab_exercise",
        options: null,
        difficulty_layer: 2,
        problem_metadata: {
          target_url: "http://localhost:3100/#/search",
        },
      },
    ]);
    await waitFor(() =>
      expect(screen.getByTestId("lab-exercise-block-stub")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("leb-trigger-advance")).toBeNull();
  });

  it("adapter maps AnswerResponse to LabExerciseSubmitResult (no confidence today)", async () => {
    // Backend does NOT currently surface confidence in AnswerResponse; the
    // adapter intentionally drops the field. If the backend ever grows one,
    // flip the pass-through in handleLabExerciseSubmit — the block supports
    // confidence already (see lab-exercise-block.test.tsx).
    await renderWithProblems(
      [
        {
          id: "lab-conf",
          question: "q",
          question_type: "lab_exercise",
          options: null,
          difficulty_layer: 2,
          problem_metadata: {
            target_url: "http://localhost:3100/#/search",
          },
        },
      ],
      {
        is_correct: true,
        correct_answer: null,
        explanation: "Good proof.",
      },
    );
    const trigger = await screen.findByTestId("leb-trigger-submit");
    fireEvent.click(trigger);
    await Promise.resolve();
    // We can't assert on the returned LabExerciseSubmitResult directly
    // (the stub awaits and discards it). The contract is enforced by the
    // TypeScript compiler (adapter return type declares confidence?: number).
    // What we CAN assert: submitAnswer was called exactly once, adapter path
    // executed. The richer adapter wiring is covered by the unit test above.
    const api = await import("@/lib/api");
    expect(api.submitAnswer).toHaveBeenCalledTimes(1);
  });
});
