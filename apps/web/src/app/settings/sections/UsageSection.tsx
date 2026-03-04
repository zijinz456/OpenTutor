"use client";

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n-context";
import { getUsageSummary } from "@/lib/api";
import type { UsageSummary } from "./types";

export function UsageSection() {
  const t = useT();
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);

  useEffect(() => {
    void loadUsage();
  }, []);

  async function loadUsage(): Promise<void> {
    setUsageLoading(true);
    try {
      setUsage(await getUsageSummary("month"));
    } catch {
      setUsage(null);
    } finally {
      setUsageLoading(false);
    }
  }

  return (
    <section data-testid="settings-usage">
      <h2 className="font-medium text-foreground mb-3">
        {t("settings.usage")}
      </h2>
      <div className="rounded-lg border border-border p-4">
        {usageLoading ? (
          <div className="h-4 w-32 bg-muted animate-pulse rounded" />
        ) : usage ? (
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-2xl font-semibold text-foreground">
                ${usage.total_cost_usd.toFixed(2)}
              </div>
              <div className="text-xs text-muted-foreground">
                {t("settings.costMonth")}
              </div>
            </div>
            <div>
              <div className="text-2xl font-semibold text-foreground">
                {(
                  (usage.total_input_tokens + usage.total_output_tokens) /
                  1000
                ).toFixed(1)}
                k
              </div>
              <div className="text-xs text-muted-foreground">
                {t("settings.tokens")}
              </div>
            </div>
            <div>
              <div className="text-2xl font-semibold text-foreground">
                {usage.total_calls}
              </div>
              <div className="text-xs text-muted-foreground">
                {t("settings.apiCalls")}
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("settings.usageUnavailable")}
          </p>
        )}
      </div>
    </section>
  );
}
