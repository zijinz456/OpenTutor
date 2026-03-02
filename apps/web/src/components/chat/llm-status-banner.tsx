"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getHealthStatus, type HealthStatus } from "@/lib/api";

/**
 * Displays a contextual banner in the chat panel when the LLM backend
 * is degraded, in mock fallback, or requires configuration.
 */
export function LlmStatusBanner() {
  const [status, setStatus] = useState<HealthStatus | null>(null);

  useEffect(() => {
    getHealthStatus()
      .then(setStatus)
      .catch(() => {});
  }, []);

  if (!status) return null;

  const llm = status.llm_status;
  if (llm === "ready") return null;

  const config: Record<string, { bg: string; border: string; text: string; label: string; message: string; showSettings: boolean }> = {
    mock_fallback: {
      bg: "bg-yellow-50 dark:bg-yellow-950/30",
      border: "border-yellow-200 dark:border-yellow-800",
      text: "text-yellow-800 dark:text-yellow-200",
      label: "Info:",
      message: "Running in mock mode — AI responses are simulated. Add an API key in Settings for full functionality.",
      showSettings: true,
    },
    degraded: {
      bg: "bg-orange-50 dark:bg-orange-950/30",
      border: "border-orange-200 dark:border-orange-800",
      text: "text-orange-800 dark:text-orange-200",
      label: "Warning:",
      message: "AI service is unstable. Responses may be slow or incomplete.",
      showSettings: false,
    },
    configuration_required: {
      bg: "bg-red-50 dark:bg-red-950/30",
      border: "border-red-200 dark:border-red-800",
      text: "text-red-800 dark:text-red-200",
      label: "Setup:",
      message: "No LLM provider configured. Go to Settings to add an API key.",
      showSettings: true,
    },
  };

  const cfg = config[llm];
  if (!cfg) return null;

  return (
    <div className={`flex items-center gap-2 px-3 py-2 text-xs border-b ${cfg.bg} ${cfg.border} ${cfg.text}`}>
      <span className="shrink-0 font-semibold">{cfg.label}</span>
      <span className="flex-1">{cfg.message}</span>
      {cfg.showSettings && (
        <Link href="/settings" className="flex items-center gap-1 font-medium underline underline-offset-2">
          Settings
        </Link>
      )}
    </div>
  );
}
