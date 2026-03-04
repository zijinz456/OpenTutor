"use client";

import { AlertTriangle, Database, Wrench } from "lucide-react";
import type { HealthStatus } from "@/lib/api";
import { useT } from "@/lib/i18n-context";

interface RuntimeAlertProps {
  health: HealthStatus | null;
  className?: string;
}

export function RuntimeAlert({ health, className }: RuntimeAlertProps) {
  const t = useT();

  if (!health) {
    return null;
  }

  const warnings: Array<{
    key: string;
    title: string;
    body: string;
    Icon: typeof AlertTriangle;
  }> = [];

  if (health.migration_required) {
    warnings.push({
      key: "migration",
      title: t("runtimeAlert.schemaTitle"),
      body: t("runtimeAlert.schemaBody"),
      Icon: Database,
    });
  }

  if (!health.code_sandbox_runtime_available) {
    warnings.push({
      key: "sandbox",
      title: t("runtimeAlert.sandboxTitle"),
      body: t("runtimeAlert.sandboxBody"),
      Icon: Wrench,
    });
  }

  if (health.llm_status === "mock_fallback" || health.llm_status === "configuration_required") {
    warnings.push({
      key: "llm",
      title: t("runtimeAlert.llmTitle"),
      body:
        health.llm_status === "configuration_required"
          ? t("runtimeAlert.llmConfigBody")
          : t("runtimeAlert.llmMockBody"),
      Icon: AlertTriangle,
    });
  } else if (health.llm_status === "degraded") {
    warnings.push({
      key: "llm-degraded",
      title: t("runtimeAlert.llmDegradedTitle"),
      body: t("runtimeAlert.llmDegradedBody"),
      Icon: AlertTriangle,
    });
  }

  if (warnings.length === 0) {
    return null;
  }

  return (
    <div className={className}>
      <div className="grid gap-3">
        {warnings.map(({ key, title, body, Icon }) => (
          <div
            key={key}
            className="rounded-xl border border-amber-300/60 bg-amber-50/80 px-4 py-3 text-amber-950 shadow-sm"
          >
            <div className="flex items-start gap-3">
              <Icon className="mt-0.5 size-4 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold">{title}</p>
                <p className="text-sm text-amber-900/85">{body}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
