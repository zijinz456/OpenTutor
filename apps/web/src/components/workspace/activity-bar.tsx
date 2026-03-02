"use client";

import { useRouter } from "next/navigation";
import { useT } from "@/lib/i18n-context";

interface ActivityBarProps {
  activeItem: string;
  onItemClick: (item: string) => void;
  items?: Array<{ id: string; title: string }>;
}

const ALL_ITEMS = [
  { id: "notes", key: "course.notes" },
  { id: "practice", key: "course.practice" },
  { id: "chat", key: "course.chat" },
  { id: "progress", key: "course.progress" },
  { id: "activity", key: "course.activity" },
  { id: "profile", key: "course.profile" },
];

export function ActivityBar({ activeItem, onItemClick, items }: ActivityBarProps) {
  const router = useRouter();
  const t = useT();
  const visibleItems = ALL_ITEMS.filter((item) =>
    items ? items.some((candidate) => candidate.id === item.id) : true,
  );

  return (
    <div className="w-[140px] bg-sidebar border-r border-sidebar-border flex flex-col py-3 px-2 gap-0.5 shrink-0">
      <button
        type="button"
        onClick={() => router.push("/")}
        title={t("course.home")}
        className="px-3 py-2 rounded-md text-xs text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors text-left"
      >
        {t("course.home")}
      </button>

      <div className="h-px bg-sidebar-border my-1.5" />

      {visibleItems.map((item) => (
        <button
          type="button"
          key={item.id}
          onClick={() => onItemClick(item.id)}
          title={t(item.key)}
          className={`px-3 py-2 rounded-md text-xs font-medium transition-colors text-left ${
            activeItem === item.id
              ? "bg-sidebar-accent text-sidebar-accent-foreground"
              : "text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent/50"
          }`}
        >
          {t(item.key)}
        </button>
      ))}

      <div className="flex-1" />

      <button
        type="button"
        onClick={() => router.push("/settings")}
        title={t("course.settings")}
        className="px-3 py-2 rounded-md text-xs text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors text-left"
      >
        {t("course.settings")}
      </button>
    </div>
  );
}
