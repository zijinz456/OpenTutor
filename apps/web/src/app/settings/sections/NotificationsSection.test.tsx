import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test-utils";
import { NotificationsSection } from "./NotificationsSection";

const listNotifications = vi.fn();
const markNotificationRead = vi.fn();
const markAllNotificationsRead = vi.fn();
const t = (key: string) => key;
const tf = (key: string, params?: Record<string, unknown>) =>
  key === "settings.notificationsUnreadCount" ? `${params?.count ?? 0} unread` : key;

vi.mock("@/lib/api", () => ({
  listNotifications: (...args: unknown[]) => listNotifications(...args),
  markNotificationRead: (...args: unknown[]) => markNotificationRead(...args),
  markAllNotificationsRead: (...args: unknown[]) => markAllNotificationsRead(...args),
}));

vi.mock("@/lib/i18n-context", () => ({
  useT: () => t,
  useTF: () => tf,
}));

function buildNotification(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "n1",
    title: "Reminder",
    body: "Review chapter 3",
    category: "study",
    read: false,
    data: null,
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("NotificationsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads notifications and supports marking a single item as read", async () => {
    listNotifications.mockResolvedValue({
      unread_count: 1,
      notifications: [buildNotification()],
    });
    markNotificationRead.mockResolvedValue(undefined);

    const { user } = render(<NotificationsSection />);
    await screen.findByText("Reminder");
    expect(screen.getByText("1 unread")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "settings.notificationsMarkRead" }));

    await waitFor(() => {
      expect(markNotificationRead).toHaveBeenCalledWith("n1");
    });
    await waitFor(() => {
      expect(screen.getByText("0 unread")).toBeInTheDocument();
    });
  });

  it("supports marking all notifications as read", async () => {
    listNotifications.mockResolvedValue({
      unread_count: 2,
      notifications: [
        buildNotification({ id: "n1", title: "First" }),
        buildNotification({ id: "n2", title: "Second" }),
      ],
    });
    markAllNotificationsRead.mockResolvedValue(undefined);

    const { user } = render(<NotificationsSection />);
    await screen.findByText("First");

    await user.click(screen.getByRole("button", { name: "notification.markAllRead" }));

    await waitFor(() => {
      expect(markAllNotificationsRead).toHaveBeenCalledTimes(1);
      expect(screen.getByText("0 unread")).toBeInTheDocument();
    });
  });

  it("renders empty state when there are no notifications", async () => {
    listNotifications.mockResolvedValue({ unread_count: 0, notifications: [] });

    render(<NotificationsSection />);

    expect(await screen.findByText("notification.empty")).toBeInTheDocument();
  });

  it("renders error state and retry action on load failure", async () => {
    listNotifications.mockRejectedValue(new Error("Request failed"));

    const { user } = render(<NotificationsSection />);
    expect(await screen.findByText("Request failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => {
      expect(listNotifications).toHaveBeenCalledTimes(2);
    });
  });
});
