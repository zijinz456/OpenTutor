import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { MessageBubble } from "./message-bubble";
import type { ChatMessage } from "@/store/chat";
import type { ChatGuardrails } from "@/lib/api/chat";

// Mock next/image to a plain <img> — matches the existing message-bubble test.
vi.mock("next/image", () => ({
  default: (props: Record<string, unknown>) => {
    const { src, alt, ...rest } = props;
    const imgProps = { ...rest };
    delete imgProps.unoptimized;
    delete imgProps.priority;
    delete imgProps.fill;
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src as string} alt={alt as string} {...imgProps} />;
  },
}));

// Radix Tooltip primitives render children in a Portal with open-on-hover
// semantics; shortcut to passthrough so tooltip content is present in the
// DOM and queryable directly.
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="citation-tooltip-content">{children}</div>
  ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <span data-testid="badge" {...props}>
      {children}
    </span>
  ),
}));

function guardrailsFixture(overrides: Partial<ChatGuardrails> = {}): ChatGuardrails {
  return {
    strict_mode: true,
    answer: "See [1] and [2].",
    confidence: 4,
    citations: [1, 2],
    citation_chunks: [
      {
        id: "chunk-a",
        source_file: "generators.md",
        snippet: "Generators yield values lazily via the yield keyword.",
      },
      {
        id: "chunk-b",
        source_file: "iterators.md",
        snippet: "Iterators implement __iter__ and __next__ for stateful iteration.",
      },
    ],
    refusal_reason: null,
    top_retrieval_score: 0.81,
    ...overrides,
  };
}

function makeAssistant(
  content: string,
  guardrails: ChatGuardrails | null,
): ChatMessage {
  return {
    id: "msg-assist-1",
    role: "assistant",
    content,
    timestamp: new Date("2026-04-22T00:00:00Z"),
    metadata: { guardrails },
  };
}

describe("MessageBubble — guardrails", () => {
  it("renders citation pills for each [N] marker backed by metadata.guardrails.citations", () => {
    const guardrails = guardrailsFixture();
    render(<MessageBubble message={makeAssistant(guardrails.answer, guardrails)} />);

    const pill1 = screen.getByTestId("citation-pill-1");
    const pill2 = screen.getByTestId("citation-pill-2");
    expect(pill1).toBeInTheDocument();
    expect(pill2).toBeInTheDocument();
    expect(pill1).toHaveTextContent("1");
    expect(pill2).toHaveTextContent("2");
  });

  it("shows source_file + snippet in the tooltip content for each pill", async () => {
    const guardrails = guardrailsFixture();
    render(<MessageBubble message={makeAssistant(guardrails.answer, guardrails)} />);

    // With Tooltip mocked to passthrough, both tooltip bodies are rendered
    // directly alongside their triggers — verify the content is attached to
    // the hover surface regardless of portal-open state.
    await waitFor(() => {
      expect(screen.getByText("generators.md")).toBeInTheDocument();
      expect(screen.getByText("iterators.md")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Generators yield values lazily/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Iterators implement __iter__/),
    ).toBeInTheDocument();

    const pill1 = screen.getByTestId("citation-pill-1");
    expect(pill1).toHaveAttribute("aria-label", "Citation 1: generators.md");
  });

  it("renders a 'Refused: no retrieval match' badge when refusal_reason is set", () => {
    const guardrails = guardrailsFixture({
      refusal_reason: "no_retrieval",
      answer: "I don't have this in your course materials.",
      citations: [],
      citation_chunks: [],
      confidence: 0,
    });
    render(<MessageBubble message={makeAssistant(guardrails.answer, guardrails)} />);

    const badge = screen.getByTestId("guardrails-refusal-badge");
    expect(badge).toHaveTextContent(/Refused: no retrieval match/i);
    // Refusal should NOT also render citation pills — they were empty anyway,
    // and the `[N]`-in-text substring path must be skipped.
    expect(screen.queryByTestId("citation-pill-1")).not.toBeInTheDocument();
    // Strict pill must not claim "X citations" for a refusal.
    expect(screen.queryByTestId("guardrails-strict-badge")).not.toBeInTheDocument();
  });

  it("dims bubble (opacity 0.7) and shows 'uncertain' badge when confidence < 3", () => {
    const guardrails = guardrailsFixture({ confidence: 2, answer: "Maybe [1]." });
    render(<MessageBubble message={makeAssistant(guardrails.answer, guardrails)} />);

    const bubble = screen
      .getByTestId("chat-message-assistant")
      .querySelector("[data-guardrails-low-confidence='true']");
    expect(bubble).not.toBeNull();
    expect((bubble as HTMLElement).style.opacity).toBe("0.7");

    const uncertainBadge = screen.getByTestId("guardrails-uncertain-badge");
    expect(uncertainBadge).toHaveTextContent("uncertain (2/5)");
  });
});
