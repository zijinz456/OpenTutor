"use client";

import { Skeleton } from "@/components/ui/skeleton"
import { useT } from "@/lib/i18n-context"

export function BlockSkeleton() {
  const t = useT()
  return (
    <div
      role="status"
      aria-label={t("block.loading")}
      className="flex items-center justify-center h-32"
    >
      <Skeleton className="h-16 w-3/4 rounded-lg" />
    </div>
  )
}
