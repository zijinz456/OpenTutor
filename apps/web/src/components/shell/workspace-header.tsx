"use client";

import Link from "next/link";
import { ArrowLeft, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n-context";
import { NotificationBell } from "@/components/shared/notification-bell";

interface WorkspaceHeaderProps {
  courseName: string;
}

export function WorkspaceHeader({
  courseName,
}: WorkspaceHeaderProps) {
  const t = useT();

  return (
    <header
      className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3"
      style={{ background: "var(--section-header)" }}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <Button
          variant="ghost"
          size="icon-xs"
          asChild
          className="shrink-0 text-muted-foreground hover:text-foreground"
          title="Home"
        >
          <Link href="/" aria-label={t("nav.back") || "Back"}>
            <ArrowLeft className="size-3.5" />
          </Link>
        </Button>

        <span className="truncate text-xs font-medium text-foreground">
          {courseName}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <NotificationBell />

        <Button
          variant="ghost"
          size="icon-xs"
          asChild
          className="text-muted-foreground hover:text-foreground"
          title="Settings"
        >
          <Link href="/settings" aria-label={t("nav.settings") || "Settings"}>
            <Settings className="size-3.5" />
          </Link>
        </Button>
      </div>
    </header>
  );
}
