import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test-utils";
import { MessageBubble } from "./message-bubble";
import type { ChatMessage } from "@/store/chat";

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

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <span data-testid="badge" {...props}>{children}</span>
  ),
}));

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "msg-1",
    role: "user",
    content: "Hello world",
    timestamp: new Date("2026-01-01T00:00:00Z"),
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("renders user message with correct test ID", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByTestId("chat-message-user")).toBeInTheDocument();
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders assistant message with correct test ID", () => {
    render(
      <MessageBubble
        message={makeMessage({ role: "assistant", content: "Hi there!" })}
      />
    );
    expect(screen.getByTestId("chat-message-assistant")).toBeInTheDocument();
    expect(screen.getByText("Hi there!")).toBeInTheDocument();
  });

  it("has correct aria-label for user messages", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByLabelText("Your message")).toBeInTheDocument();
  });

  it("has correct aria-label for assistant messages", () => {
    render(
      <MessageBubble
        message={makeMessage({ role: "assistant", content: "Reply" })}
      />
    );
    expect(screen.getByLabelText("Assistant message")).toBeInTheDocument();
  });

  it("renders action cards for assistant messages with actions", () => {
    const msg = makeMessage({
      role: "assistant",
      content: "Let me help",
      metadata: {
        actions: [
          { action: "add_block", value: "quiz" },
          { action: "add_block", value: "flashcards" },
        ],
      },
    });
    render(<MessageBubble message={msg} />);
    expect(screen.getByText("Let me help")).toBeInTheDocument();
  });

  it("renders verifier details when present", () => {
    const msg = makeMessage({
      role: "assistant",
      content: "Answer",
      metadata: {
        verifier: { status: "pass", code: "V001", message: "All good" },
        verifier_diagnostics: {
          request_coverage: 0.85,
          evidence_coverage: 0.9,
        },
      },
    });
    render(<MessageBubble message={msg} />);
    expect(screen.getByText("Why this answer")).toBeInTheDocument();
  });

  it("shows ellipsis for empty content without images", () => {
    render(<MessageBubble message={makeMessage({ content: "" })} />);
    expect(screen.getByText("...")).toBeInTheDocument();
  });

  it("hides content for image-only messages", () => {
    const msg = makeMessage({
      content: "(image)",
      images: [{ data: "abc", media_type: "image/png", filename: "test.png" }],
    });
    render(<MessageBubble message={msg} />);
    // Should not display "(image)" text
    expect(screen.queryByText("(image)")).not.toBeInTheDocument();
  });

});
