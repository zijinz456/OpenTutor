import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test-utils";
import { SendButton } from "./send-button";

describe("SendButton", () => {
  it("renders send button when not streaming", () => {
    render(
      <SendButton isStreaming={false} canSend={true} onSend={vi.fn()} onStop={vi.fn()} />
    );
    expect(screen.getByTestId("chat-send")).toBeInTheDocument();
    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
  });

  it("renders stop button when streaming", () => {
    render(
      <SendButton isStreaming={true} canSend={false} onSend={vi.fn()} onStop={vi.fn()} />
    );
    expect(screen.getByTestId("chat-stop")).toBeInTheDocument();
    expect(screen.getByLabelText("Stop generating")).toBeInTheDocument();
  });

  it("disables send button when canSend is false", () => {
    render(
      <SendButton isStreaming={false} canSend={false} onSend={vi.fn()} onStop={vi.fn()} />
    );
    const btn = screen.getByTestId("chat-send");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-disabled", "true");
  });

  it("calls onSend when clicked", async () => {
    const onSend = vi.fn();
    const { user } = render(
      <SendButton isStreaming={false} canSend={true} onSend={onSend} onStop={vi.fn()} />
    );
    await user.click(screen.getByTestId("chat-send"));
    expect(onSend).toHaveBeenCalledOnce();
  });

  it("calls onStop when streaming and clicked", async () => {
    const onStop = vi.fn();
    const { user } = render(
      <SendButton isStreaming={true} canSend={false} onSend={vi.fn()} onStop={onStop} />
    );
    await user.click(screen.getByTestId("chat-stop"));
    expect(onStop).toHaveBeenCalledOnce();
  });
});
