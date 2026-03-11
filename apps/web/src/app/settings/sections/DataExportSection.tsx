"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n-context";
import { downloadExportSession } from "@/lib/api";
import { trackApiFailure } from "@/lib/error-telemetry";
import { toast } from "sonner";

export function DataExportSection() {
  const t = useT();
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setDownloading(true);
    setError(null);
    try {
      const { blob, fileName } = await downloadExportSession();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = fileName || "opentutor-session-export.csv";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      trackApiFailure("download", err, { endpoint: "/export/session" });
      const message = err instanceof Error ? err.message : t("settings.exportFailed");
      setError(message);
      toast.error(t("settings.exportFailed"), { description: message });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <section data-testid="settings-export">
      <h2 className="font-medium text-foreground mb-3">
        {t("settings.export")}
      </h2>
      <p className="text-sm text-muted-foreground mb-3">
        {t("settings.exportDescription")}
      </p>
      <Button variant="outline" size="sm" disabled={downloading} onClick={() => void handleExport()}>
        {downloading ? "..." : t("settings.exportButton")}
      </Button>
      {error ? (
        <p className="mt-2 text-xs text-destructive">{error}</p>
      ) : null}
    </section>
  );
}
