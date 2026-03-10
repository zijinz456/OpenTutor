"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { Search, X, FileText, ArrowRight } from "lucide-react";
import { useCourseStore } from "@/store/course";
import { useFocusTrap } from "@/hooks/use-focus-trap";
import type { ContentNode } from "@/lib/api";

function flattenTree(nodes: ContentNode[], courseId: string): Array<{ id: string; title: string; content: string; courseId: string }> {
  const results: Array<{ id: string; title: string; content: string; courseId: string }> = [];
  for (const node of nodes) {
    if (node.title) {
      results.push({ id: node.id, title: node.title, content: node.content ?? "", courseId });
    }
    if (node.children?.length) {
      results.push(...flattenTree(node.children, courseId));
    }
  }
  return results;
}

interface SearchDialogProps {
  open: boolean;
  onClose: () => void;
  courseId?: string;
}

export function SearchDialog({ open, onClose, courseId }: SearchDialogProps) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const contentTree = useCourseStore((s) => s.contentTree);
  const courses = useCourseStore((s) => s.courses);
  const handleClose = useCallback(() => {
    setQuery("");
    onClose();
  }, [onClose]);

  // Trap focus within the search dialog
  useFocusTrap(dialogRef, open);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, handleClose]);

  // Local search through content tree
  const results = useCallback(() => {
    if (!query.trim() || query.length < 2) return [];
    const q = query.toLowerCase();
    const cid = courseId ?? courses[0]?.id ?? "";
    const flat = flattenTree(contentTree, cid);
    return flat
      .filter((item) => item.title.toLowerCase().includes(q) || item.content.toLowerCase().includes(q))
      .slice(0, 10)
      .map((item) => {
        // Extract snippet around match
        const contentLower = item.content.toLowerCase();
        const matchIdx = contentLower.indexOf(q);
        const snippet = matchIdx >= 0
          ? item.content.slice(Math.max(0, matchIdx - 40), matchIdx + q.length + 60).trim()
          : item.content.slice(0, 100).trim();
        return { ...item, snippet };
      });
  }, [query, contentTree, courseId, courses])();

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" onClick={handleClose} />

      {/* Dialog */}
      <div ref={dialogRef} role="dialog" aria-label="Search notes and concepts" aria-modal="true" className="relative w-full max-w-lg mx-4 bg-card rounded-2xl card-shadow overflow-hidden animate-fade-in">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/60">
          <Search className="size-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search notes and concepts"
            placeholder="Search notes, concepts..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
          />
          {query && (
            <button onClick={() => setQuery("")} aria-label="Clear search" className="text-muted-foreground hover:text-foreground">
              <X className="size-3.5" />
            </button>
          )}
          <kbd className="text-[10px] text-muted-foreground border border-border/60 rounded-full px-1.5 py-0.5">ESC</kbd>
        </div>

        {/* Results */}
        <div role="list" aria-label="Search results" className="max-h-[50vh] overflow-y-auto scrollbar-thin">
          {query.length >= 2 && results.length === 0 && (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-muted-foreground">No results found for &quot;{query}&quot;</p>
            </div>
          )}
          {results.map((r) => (
            <button
              key={r.id}
              type="button"
              role="listitem"
              onClick={() => {
                const targetCourseId = courseId ?? r.courseId;
                router.push(`/course/${targetCourseId}/unit/${r.id}`);
                handleClose();
              }}
              className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-muted/50 transition-colors border-b border-border/60 last:border-0"
            >
              <FileText className="size-4 text-muted-foreground shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{r.title}</p>
                {r.snippet && (
                  <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{r.snippet}</p>
                )}
              </div>
              <ArrowRight className="size-3.5 text-muted-foreground shrink-0 mt-1" />
            </button>
          ))}
          {!query && (
            <div className="px-4 py-6 text-center">
              <p className="text-xs text-muted-foreground">Type to search through your notes and concepts</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
