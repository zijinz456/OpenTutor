import { useCallback, useEffect, useRef, useState } from "react";
import type { GeneratedBatchSummaryBase } from "@/lib/api/client";
import { useWorkspaceStore } from "@/store/workspace";
import { toast } from "sonner";

interface SaveResult {
  replaced: boolean;
  version: number;
}

interface UseBatchManagerOptions<TBatch extends GeneratedBatchSummaryBase> {
  courseId: string;
  /** Key into workspace sectionRefreshKey, e.g. "notes", "practice", "plan" */
  refreshSection: string;
  listFn: (courseId: string) => Promise<TBatch[]>;
}

/**
 * Shared hook for managing generated asset batches (notes, flashcards, plans).
 *
 * Encapsulates: batch loading, refresh-on-key-change, latest batch detection,
 * and save with "Replace Latest" / "Save New" semantics.
 */
export function useBatchManager<TBatch extends GeneratedBatchSummaryBase>({
  courseId,
  refreshSection,
  listFn,
}: UseBatchManagerOptions<TBatch>) {
  const refreshKey = useWorkspaceStore(
    (s) => s.sectionRefreshKey[refreshSection],
  );
  const [batches, setBatches] = useState<TBatch[]>([]);
  const [saving, setSaving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadBatches = useCallback(async () => {
    try {
      setBatches(await listFn(courseId));
    } catch {
      setBatches([]);
    }
  }, [courseId, listFn]);

  // Debounced refresh: prevents duplicate requests on rapid section refreshes
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void loadBatches();
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [loadBatches, refreshKey]);

  const latestBatch = batches.find((b) => b.is_active) ?? null;

  /** Wrap a save call with loading state and toast feedback. */
  const wrapSave = useCallback(
    async (saveFn: () => Promise<SaveResult>) => {
      setSaving(true);
      try {
        const result = await saveFn();
        toast.success(
          result.replaced
            ? `Replaced with version ${result.version}`
            : "Saved successfully",
        );
        await loadBatches();
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : "Failed to save",
        );
      } finally {
        setSaving(false);
      }
    },
    [loadBatches],
  );

  return { batches, saving, loadBatches, latestBatch, wrapSave };
}
