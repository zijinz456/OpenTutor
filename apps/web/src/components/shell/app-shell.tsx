"use client";

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { TREE_WIDTH, TREE_COLLAPSED_WIDTH, CHAT_MIN_HEIGHT, CHAT_MAX_HEIGHT } from "@/lib/constants";

interface AppShellProps {
  courseId: string;
  /** Left panel: course content tree. */
  tree: ReactNode;
  /** Right area: active section content. */
  children: ReactNode;
  /** Bottom panel: chat input + messages. */
  chat: ReactNode;
}

/**
 * VS Code-style workspace shell.
 *
 * ┌──────────┬──────────────────────┐
 * │  tree    │  section content     │
 * │  panel   │  (children)          │
 * ├──────────┴──────────────────────┤  ← drag handle
 * │  chat panel (full width)        │
 * └─────────────────────────────────┘
 */
export function AppShell({ courseId: _courseId, tree, children, chat }: AppShellProps) {
  const treeCollapsed = useWorkspaceStore((s) => s.treeCollapsed);
  const chatHeight = useWorkspaceStore((s) => s.chatHeight);
  const setChatHeight = useWorkspaceStore((s) => s.setChatHeight);

  /* ---------- Resize drag logic ---------- */
  const dragging = useRef(false);
  const shellRef = useRef<HTMLDivElement>(null);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      dragging.current = true;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging.current || !shellRef.current) return;
      const rect = shellRef.current.getBoundingClientRect();
      const totalHeight = rect.height;
      /* Distance from bottom of the shell to the pointer position gives chat height. */
      const chatPx = rect.bottom - e.clientY;
      const ratio = chatPx / totalHeight;
      setChatHeight(Math.max(CHAT_MIN_HEIGHT, Math.min(CHAT_MAX_HEIGHT, ratio)));
    },
    [setChatHeight],
  );

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  /* Cancel drag if pointer leaves the window. */
  useEffect(() => {
    const cancel = () => {
      dragging.current = false;
    };
    window.addEventListener("pointerup", cancel);
    return () => window.removeEventListener("pointerup", cancel);
  }, []);

  const treeWidth = treeCollapsed ? TREE_COLLAPSED_WIDTH : TREE_WIDTH;

  return (
    <div ref={shellRef} className="relative flex h-full flex-col overflow-hidden">
      {/* ── Top area: tree + section content ── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left: course tree */}
        <aside
          className="shrink-0 overflow-hidden border-r border-border"
          style={{
            width: treeWidth,
            transition: `width var(--duration-normal, 300ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1))`,
            background: "var(--tree-bg)",
          }}
          aria-label="Course tree"
        >
          <div
            className="h-full overflow-y-auto overflow-x-hidden"
            style={{ width: treeWidth }}
          >
            {tree}
          </div>
        </aside>

        {/* Right: active section content */}
        <main
          className="flex-1 min-w-0 overflow-hidden"
          style={{ background: "var(--section-bg)" }}
        >
          {children}
        </main>
      </div>

      {/* ── Resize handle ── */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize chat panel"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className="group relative z-10 flex h-1.5 shrink-0 cursor-row-resize items-center justify-center border-y border-border bg-muted/60 hover:bg-primary/10 active:bg-primary/20 select-none touch-none"
      >
        {/* Visual grip indicator */}
        <span className="h-0.5 w-8 rounded-full bg-muted-foreground/30 group-hover:bg-primary/50 transition-colors" />
      </div>

      {/* ── Bottom: chat panel ── */}
      <section
        className="shrink-0 overflow-hidden"
        style={{ height: `${chatHeight * 100}%` }}
        aria-label="Chat panel"
      >
        {chat}
      </section>
    </div>
  );
}
