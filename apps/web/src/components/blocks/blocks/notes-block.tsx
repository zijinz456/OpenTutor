"use client";

import { NotesSection } from "@/components/sections/notes-section";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function NotesBlock({ courseId, aiActionsEnabled }: BlockComponentProps) {
  return (
    <div role="region" aria-label="Notes">
      <NotesSection courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
    </div>
  );
}
