import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { ChatInput } from "./chat-input";

// Mock all dependencies

vi.mock("@/store/chat", () => ({
  useChatStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      isStreaming: false,
      sendMessage: vi.fn(),
      abortStream: vi.fn(),
    }),
}));

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ activeSection: "notes", spaceLayout: { mode: "self_paced", blocks: [] } }),
    {
      getState: () => ({
        activeSection: "notes",
        spaceLayout: { mode: "self_paced", blocks: [] },
      }),
    },
  ),
}));

vi.mock("@/store/course", () => ({
  useCourseStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      fetchContentTree: vi.fn(),
      fetchIngestionJobs: vi.fn(),
    }),
}));

vi.mock("@/lib/auth", () => ({
  getStoredAccessToken: () => undefined,
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("@/components/chat/use-image-attachments", () => ({
  useImageAttachments: () => ({
    clearImages: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDragOver: vi.fn(),
    handleDrop: vi.fn(),
    handleImageChange: vi.fn(),
    handleImageClick: vi.fn(),
    handlePaste: vi.fn(),
    imageInputRef: { current: null },
    isDragOver: false,
    pendingImages: [],
    removeImage: vi.fn(),
  }),
}));

vi.mock("@/components/chat/image-preview-strip", () => ({
  ImagePreviewStrip: () => null,
}));

vi.mock("@/components/chat/attachment-buttons", () => ({
  AttachmentButtons: () => <div data-testid="attachment-buttons" />,
}));

vi.mock("@/components/chat/send-button", () => ({
  SendButton: ({ canSend }: { canSend: boolean }) => (
    <button data-testid="send-button" disabled={!canSend}>
      Send
    </button>
  ),
}));

describe("ChatInput", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders textarea with correct aria-label", () => {
    render(<ChatInput courseId="test-course" />);
    const textarea = screen.getByLabelText("Message input");
    expect(textarea).toBeInTheDocument();
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  it("renders placeholder text when empty", () => {
    render(<ChatInput courseId="test-course" />);
    const textarea = screen.getByPlaceholderText("Ask anything...");
    expect(textarea).toBeInTheDocument();
  });

  it("accepts text input", async () => {
    const { user } = render(<ChatInput courseId="test-course" />);
    const textarea = screen.getByTestId("chat-input");
    await user.type(textarea, "Hello world");
    expect(textarea).toHaveValue("Hello world");
  });

  it("shows send button enabled when text is present", async () => {
    const { user } = render(<ChatInput courseId="test-course" />);
    const textarea = screen.getByTestId("chat-input");
    await user.type(textarea, "Hello");
    await waitFor(() => {
      expect(screen.getByTestId("send-button")).not.toBeDisabled();
    });
  });

  it("disables textarea when disabled prop is true", () => {
    render(<ChatInput courseId="test-course" disabled />);
    const textarea = screen.getByTestId("chat-input");
    expect(textarea).toBeDisabled();
  });

  it("shows disabled placeholder when disabled", () => {
    render(<ChatInput courseId="test-course" disabled />);
    const textarea = screen.getByPlaceholderText("chat.disabledNeedLlm");
    expect(textarea).toBeInTheDocument();
  });

});
