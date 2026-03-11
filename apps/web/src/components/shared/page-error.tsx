"use client";

import { useT } from "@/lib/i18n-context";
import { Button } from "@/components/ui/button";
import { AlertCircle, WifiOff, ShieldAlert, ServerCrash, Clock } from "lucide-react";

type ErrorCategory = "network" | "auth" | "server" | "rateLimit" | "generic";

function classifyError(error: Error): ErrorCategory {
  const msg = error.message?.toLowerCase() ?? "";
  // Network errors: TypeError from fetch, or explicit network mentions
  if (error instanceof TypeError && (msg.includes("fetch") || msg.includes("network"))) {
    return "network";
  }
  if (msg.includes("network") || msg.includes("offline") || msg.includes("failed to fetch")) {
    return "network";
  }
  // Auth errors
  if (msg.includes("401") || msg.includes("403") || msg.includes("unauthorized") || msg.includes("forbidden")) {
    return "auth";
  }
  // Rate limit
  if (msg.includes("429") || msg.includes("rate limit") || msg.includes("too many")) {
    return "rateLimit";
  }
  // Server errors
  if (msg.includes("500") || msg.includes("502") || msg.includes("503") || msg.includes("server")) {
    return "server";
  }
  return "generic";
}

const CATEGORY_ICONS: Record<ErrorCategory, typeof AlertCircle> = {
  network: WifiOff,
  auth: ShieldAlert,
  server: ServerCrash,
  rateLimit: Clock,
  generic: AlertCircle,
};

interface PageErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
  section?: string;
}

export function PageError({ error, reset, section }: PageErrorProps) {
  const t = useT();
  const category = classifyError(error);
  const Icon = CATEGORY_ICONS[category];

  const sectionTitleKey = `error.title.${section}`;
  const sectionTitle = section ? t(sectionTitleKey) : "";
  const title = section && sectionTitle !== sectionTitleKey
    ? sectionTitle
    : t("error.title.app");
  const hintKey = `error.hint.${category}`;
  const hint = t(hintKey) !== hintKey ? t(hintKey) : t("error.hint.generic");

  return (
    <div role="alert" className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center max-w-md px-6">
        <div className="flex justify-center mb-3">
          <Icon className="size-8 text-muted-foreground" />
        </div>
        <h2 className="text-lg font-semibold mb-2">{title}</h2>
        <p className="text-sm text-muted-foreground mb-1">
          {hint}
        </p>
        {error.message && (
          <p className="text-xs text-muted-foreground/70 mb-4">
            {error.message}
          </p>
        )}
        <Button onClick={reset} variant="default" size="sm">
          {t("error.retry")}
        </Button>
      </div>
    </div>
  );
}
