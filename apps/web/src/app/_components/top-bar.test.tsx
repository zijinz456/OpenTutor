import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TopBar } from "./top-bar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/tracks",
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.HTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/shared/today-tools-popover", () => ({
  TodayToolsPopover: () => (
    <button type="button" data-testid="today-tools-trigger">
      Today tools
    </button>
  ),
}));

describe("<TopBar>", () => {
  it("renders nav links, today-tools trigger, and streak chip", () => {
    render(<TopBar />);

    expect(screen.getByTestId("top-bar-link-tracks")).toHaveAttribute(
      "href",
      "/tracks",
    );
    expect(screen.getByTestId("top-bar-link-review")).toHaveAttribute(
      "href",
      "/session/daily",
    );
    expect(screen.getByTestId("top-bar-link-recap")).toHaveAttribute(
      "href",
      "/recap",
    );
    expect(screen.getByTestId("today-tools-trigger")).toBeInTheDocument();
    expect(screen.getByTestId("top-bar-streak-chip")).toHaveTextContent("🔥 7");
  });
});
