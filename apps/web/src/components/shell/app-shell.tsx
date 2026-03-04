"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useWorkspaceStore } from "@/store/workspace";
import { TREE_WIDTH, TREE_COLLAPSED_WIDTH, CHAT_MIN_HEIGHT, CHAT_MAX_HEIGHT } from "@/lib/constants";

interface AppShellProps {
  courseId: string;
  /** Left panel: course content tree. */
  tree: ReactNode;
  /** Right area: active section content. */
  children: ReactNode;
  /** Bottom panel: chat input + messages. */
  chat?: ReactNode;
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
export function AppShell({ tree, children, chat }: AppShellProps) {
  const treeCollapsed = useWorkspaceStore((s) => s.treeCollapsed);
  const chatHeight = useWorkspaceStore((s) => s.chatHeight);
  const setChatHeight = useWorkspaceStore((s) => s.setChatHeight);
  const [isMobile, setIsMobile] = useState(false);

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

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  const treeWidth = treeCollapsed ? TREE_COLLAPSED_WIDTH : TREE_WIDTH;
  const treePanelStyle = isMobile
    ? {
        width: "100%",
        maxHeight: treeCollapsed ? `${TREE_COLLAPSED_WIDTH}px` : "32vh",
        transition: `max-height var(--duration-normal, 300ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1))`,
        background: "var(--tree-bg)",
      }
    : {
        width: treeWidth,
        transition: `width var(--duration-normal, 300ms) var(--ease-out-expo, cubic-bezier(0.16,1,0.3,1))`,
        background: "var(--tree-bg)",
      };
  const chatPanelStyle = isMobile ? { height: "38vh" } : { height: `${chatHeight * 100}%` };

  return (
    <div ref={shellRef} className="relative flex h-full flex-col overflow-hidden">
      {/* ── Top area: tree + section content ── */}
      <div className={`flex flex-1 min-h-0 overflow-hidden ${isMobile ? "flex-col" : ""}`}>
        {/* Left: course tree */}
        <aside
          className={`shrink-0 overflow-hidden border-border ${isMobile ? "border-b" : "border-r"}`}
          style={treePanelStyle}
          aria-label="Course tree"
        >
          <div
            className="h-full overflow-y-auto overflow-x-hidden"
            style={isMobile ? undefined : { width: treeWidth }}
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

      {chat ? (
        <>
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label="Resize chat panel"
            onPointerDown={isMobile ? undefined : onPointerDown}
            onPointerMove={isMobile ? undefined : onPointerMove}
            onPointerUp={isMobile ? undefined : onPointerUp}
            className={`group relative z-10 flex shrink-0 items-center justify-center border-border bg-muted/60 select-none touch-none hover:bg-primary/10 active:bg-primary/20 ${isMobile ? "h-3 cursor-default border-y" : "h-1.5 cursor-row-resize border-y"}`}
          >
            <span className="h-0.5 w-8 rounded-full bg-muted-foreground/30 transition-colors group-hover:bg-primary/50" />
          </div>

          <section
            className="shrink-0 overflow-hidden"
            style={chatPanelStyle}
            aria-label="Chat panel"
          >
            {chat}
          </section>
        </>
      ) : null}
    </div>
  );
}
