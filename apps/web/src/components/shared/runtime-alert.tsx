"use client";

import { useState } from "react";
import { AlertTriangle, Database, X } from "lucide-react";
import type { HealthStatus } from "@/lib/api";
import { useT } from "@/lib/i18n-context";

interface RuntimeAlertProps {
  health: HealthStatus | null;
  className?: string;
}

export function RuntimeAlert({ health, className }: RuntimeAlertProps) {
  const t = useT();
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  if (!health) {
    return null;
  }

  const warnings: Array<{
    key: string;
    title: string;
    body: string;
    Icon: typeof AlertTriangle;
    dismissable: boolean;
  }> = [];

  if (health.migration_required) {
    warnings.push({
      key: "migration",
      title: t("runtimeAlert.schemaTitle"),
      body: t("runtimeAlert.schemaBody"),
      Icon: Database,
      dismissable: false,
    });
  }

  // Sandbox warning removed — Docker/Podman is optional and most users don't need it.
  // Code execution gracefully degrades with a per-action message when attempted.

  if (health.llm_status === "mock_fallback" || health.llm_status === "configuration_required") {
    warnings.push({
      key: "llm",
      title: t("runtimeAlert.llmTitle"),
      body:
        health.llm_status === "configuration_required"
          ? t("runtimeAlert.llmConfigBody")
          : t("runtimeAlert.llmMockBody"),
      Icon: AlertTriangle,
      dismissable: false,
    });
  } else if (health.llm_status === "degraded") {
    warnings.push({
      key: "llm-degraded",
      title: t("runtimeAlert.llmDegradedTitle"),
      body: t("runtimeAlert.llmDegradedBody"),
      Icon: AlertTriangle,
      dismissable: true,
    });
  }

  const visible = warnings.filter((w) => !dismissed.has(w.key));
  if (visible.length === 0) {
    return null;
  }

  return (
    <div className={className}>
      <div className="grid gap-3">
        {visible.map(({ key, title, body, Icon, dismissable }) => (
          <div
            key={key}
            role="alert"
            className="rounded-2xl border border-amber-300/60 bg-amber-50/80 px-4 py-3 text-amber-950 card-shadow"
          >
            <div className="flex items-start gap-3">
              <Icon className="mt-0.5 size-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{title}</p>
                <p className="text-sm text-amber-900/85">{body}</p>
              </div>
              {dismissable && (
                <button
                  type="button"
                  onClick={() => setDismissed((prev) => new Set(prev).add(key))}
                  className="mt-0.5 shrink-0 text-amber-600 hover:text-amber-900 transition-colors"
                  aria-label="Dismiss"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
