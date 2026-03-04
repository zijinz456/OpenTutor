"use client";

import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n-context";
import { getExportSessionUrl } from "@/lib/api";

export function DataExportSection() {
  const t = useT();

  return (
    <section data-testid="settings-export">
      <h2 className="font-medium text-foreground mb-3">
        {t("settings.export")}
      </h2>
      <p className="text-sm text-muted-foreground mb-3">
        {t("settings.exportDescription")}
      </p>
      <a href={getExportSessionUrl()} download>
        <Button variant="outline" size="sm">
          {t("settings.exportButton")}
        </Button>
      </a>
    </section>
  );
}
