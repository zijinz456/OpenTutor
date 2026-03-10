"use client";

import { useState, useMemo } from "react";
import { Plus, Lock } from "lucide-react";
import { USER_ADDABLE_BLOCKS, BLOCK_REGISTRY } from "@/lib/block-system/registry";
import { useWorkspaceStore } from "@/store/workspace";
import { useCourseStore } from "@/store/course";
import { isBlockUnlocked, getUnlockContext } from "@/lib/block-system/feature-unlock";
import { useParams } from "next/navigation";
import { useT } from "@/lib/i18n-context";
import { recordBlockEvent } from "@/hooks/use-block-engagement";

export function BlockPalette() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const addBlock = useWorkspaceStore((s) => s.addBlock);
  const mode = useWorkspaceStore((s) => s.spaceLayout.mode);
  const courses = useCourseStore((s) => s.courses);
  const params = useParams();
  const courseId = (params?.id as string) ?? "";

  const unlockCtx = useMemo(
    () => getUnlockContext(courseId, courses.length),
    [courseId, courses.length],
  );
  const ctxWithMode = useMemo(
    () => ({ ...unlockCtx, mode }),
    [unlockCtx, mode],
  );

  return (
    <div className="relative flex justify-center">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t("block.addBlock")}
        aria-expanded={open}
        aria-haspopup="menu"
        className="inline-flex items-center gap-1.5 px-5 py-2.5 text-sm text-muted-foreground hover:text-foreground border border-dashed border-border rounded-full hover:border-brand/40 hover:bg-brand-muted/30 transition-all"
      >
        <Plus className="size-4" />
        {t("block.addBlock")}
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />

          {/* Palette dropdown */}
          <div role="menu" aria-label="Add block" className="absolute bottom-full mb-2 z-50 w-72 max-h-80 overflow-auto rounded-2xl bg-popover p-2 animate-slide-up" style={{ boxShadow: "var(--shadow-elevated)" }}>
            {USER_ADDABLE_BLOCKS.map((type) => {
              const entry = BLOCK_REGISTRY[type];
              if (!entry) return null;
              const { unlocked, unlockHint } = isBlockUnlocked(type, ctxWithMode);
              return (
                <button
                  key={type}
                  type="button"
                  role="menuitem"
                  disabled={!unlocked}
                  onClick={() => {
                    if (!unlocked) return;
                    addBlock(type);
                    recordBlockEvent(courseId, type, "manual_add");
                    setOpen(false);
                  }}
                  className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-left transition-colors ${
                    unlocked
                      ? "hover:bg-accent"
                      : "opacity-50 cursor-not-allowed"
                  }`}
                >
                  <div className="flex flex-col min-w-0 flex-1">
                    <span className="text-sm font-medium text-foreground">{entry.label}</span>
                    <span className="text-xs text-muted-foreground truncate">
                      {unlocked ? entry.description : unlockHint}
                    </span>
                  </div>
                  {!unlocked && <Lock className="size-3.5 text-muted-foreground shrink-0" />}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
