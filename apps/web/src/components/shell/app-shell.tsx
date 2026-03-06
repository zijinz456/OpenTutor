"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { TREE_COLLAPSED_WIDTH, CHAT_MIN_HEIGHT, CHAT_MAX_HEIGHT } from "@/lib/constants";

interface AppShellProps {
  courseId: string;
  tree: ReactNode;
  children: ReactNode;
  chat?: ReactNode;
}

/**
 * VS Code-style shell using CSS Grid.
 *
 * Grid layout (desktop):
 *   columns: [sidebar] [v-sep] [content]
 *   rows:    [top]     [h-sep] [chat]
 *
 * Sidebar spans row 1 only.
 * Chat spans all columns (full width).
 * Both separators are draggable.
 */
export function AppShell({ tree, children, chat }: AppShellProps) {
  const treeCollapsed = useWorkspaceStore((s) => s.treeCollapsed);
  const treeWidth = useWorkspaceStore((s) => s.treeWidth);
  const setTreeWidth = useWorkspaceStore((s) => s.setTreeWidth);
  const chatHeight = useWorkspaceStore((s) => s.chatHeight);
  const setChatHeight = useWorkspaceStore((s) => s.setChatHeight);
  const [isMobile, setIsMobile] = useState(false);

  const shellRef = useRef<HTMLDivElement>(null);
  const dragAxis = useRef<"x" | "y" | null>(null);

  const onTreeDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragAxis.current = "x";
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onChatDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragAxis.current = "y";
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragAxis.current || !shellRef.current) return;
      const rect = shellRef.current.getBoundingClientRect();
      if (dragAxis.current === "x") {
        setTreeWidth(e.clientX - rect.left);
      } else {
        const ratio = (rect.bottom - e.clientY) / rect.height;
        setChatHeight(Math.max(CHAT_MIN_HEIGHT, Math.min(CHAT_MAX_HEIGHT, ratio)));
      }
    },
    [setChatHeight, setTreeWidth],
  );

  const onPointerUp = useCallback(() => { dragAxis.current = null; }, []);

  useEffect(() => {
    const cancel = () => { dragAxis.current = null; };
    window.addEventListener("pointerup", cancel);
    return () => window.removeEventListener("pointerup", cancel);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const sidebarW = treeCollapsed ? TREE_COLLAPSED_WIDTH : treeWidth;
  const showVSep = !isMobile && !treeCollapsed;

  /* fr units: top area gets (1-chatHeight), chat gets chatHeight.
     minmax(0, Xfr) ensures cells can shrink (like min-height: 0). */
  const topFr = chat ? 1 - chatHeight : 1;
  const chatFr = chatHeight;

  const gridStyle: React.CSSProperties = isMobile
    ? { display: "flex", flexDirection: "column" }
    : {
        display: "grid",
        gridTemplateColumns: `${sidebarW}px ${showVSep ? "4px" : "0px"} minmax(0, 1fr)`,
        gridTemplateRows: chat
          ? `minmax(0, ${topFr}fr) 6px minmax(0, ${chatFr}fr)`
          : "minmax(0, 1fr)",
      };

  if (isMobile) {
    // Mobile: simple flex stack
    return (
      <div ref={shellRef} className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <aside className="shrink-0 overflow-auto border-b border-border" style={{ maxHeight: treeCollapsed ? TREE_COLLAPSED_WIDTH : "32vh", background: "var(--tree-bg)" }}>
          {tree}
        </aside>
        <main className="flex-1 flex flex-col min-h-0 overflow-hidden">{children}</main>
        {chat ? (
          <>
            <div className="shrink-0 h-3 border-y border-border bg-muted/60" />
            <div className="shrink-0 overflow-hidden" style={{ height: "38vh" }}>{chat}</div>
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div
      ref={shellRef}
      className="flex-1 min-h-0 overflow-hidden"
      style={gridStyle}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      {/* Row 1, Col 1: Sidebar */}
      <aside
        className="overflow-auto"
        style={{ gridRow: 1, gridColumn: 1, background: "var(--tree-bg)" }}
      >
        {tree}
      </aside>

      {/* Row 1, Col 2: Vertical separator */}
      {showVSep ? (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          onPointerDown={onTreeDown}
          className="cursor-col-resize bg-border hover:bg-primary/30 active:bg-primary/40 select-none touch-none"
          style={{ gridRow: 1, gridColumn: 2 }}
        />
      ) : null}

      {/* Row 1, Col 3: Main content */}
      <main
        className="flex flex-col min-w-0 min-h-0 overflow-hidden"
        style={{ gridRow: 1, gridColumn: 3 }}
      >
        {children}
      </main>

      {chat ? (
        <>
          {/* Row 2, full width: Horizontal separator */}
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize chat panel"
            onPointerDown={onChatDown}
            className="flex items-center justify-center border-y border-border bg-muted/60 cursor-row-resize select-none touch-none hover:bg-primary/20 active:bg-primary/30"
            style={{ gridRow: 2, gridColumn: "1 / -1" }}
          >
            <span className="h-0.5 w-8 rounded-full bg-muted-foreground/30" />
          </div>

          {/* Row 3, full width: Chat */}
          <div
            className="min-h-0 overflow-hidden"
            style={{ gridRow: 3, gridColumn: "1 / -1" }}
          >
            {chat}
          </div>
        </>
      ) : null}
    </div>
  );
}
