"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { TodayToolsPopover } from "@/components/shared/today-tools-popover";

const NAV_ITEMS = [
  { href: "/tracks", label: "Tracks" },
  { href: "/session/daily", label: "Review" },
  { href: "/recap", label: "Recap" },
];

export function TopBar() {
  const pathname = usePathname();

  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-border/80 bg-background/92 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="font-display shrink-0 text-base font-semibold tracking-tight text-foreground"
        >
          LearnDopamine
        </Link>

        <nav className="hidden items-center gap-2 md:flex">
          {NAV_ITEMS.map((item) => {
            const active =
              pathname === item.href ||
              (item.href === "/tracks" && pathname?.startsWith("/tracks"));
            return (
              <Link
                key={item.href}
                href={item.href}
                data-testid={`top-bar-link-${item.label.toLowerCase()}`}
                className={cn(
                  "rounded-full px-3 py-1 text-sm font-medium transition-colors",
                  active
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <TodayToolsPopover />
          <span
            data-testid="top-bar-streak-chip"
            className="inline-flex h-9 items-center rounded-full border border-border/80 bg-card/80 px-3 text-sm font-medium text-foreground"
          >
            🔥 7
          </span>
        </div>
      </div>
    </header>
  );
}
