"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n-context";
import {
  getLlmStatusMeta,
  getLocalBetaIssueMeta,
  type HealthStatus,
} from "./types";

interface RuntimeStatusSectionProps {
  health: HealthStatus | null;
  healthLoading: boolean;
  onRefresh: () => void;
}

export function RuntimeStatusSection({
  health,
  healthLoading,
  onRefresh,
}: RuntimeStatusSectionProps) {
  const t = useT();
  const llmStatusMeta = getLlmStatusMeta(t);
  const localBetaIssueMeta = getLocalBetaIssueMeta(t);
  const statusMeta = health ? llmStatusMeta[health.llm_status] : null;
  const blockers = health?.local_beta_blockers ?? [];
  const warnings = health?.local_beta_warnings ?? [];
  const databaseBackend = health?.database_backend ?? t("settings.unknown");
  const getIssueLabel = (item: string) =>
    localBetaIssueMeta[item as keyof typeof localBetaIssueMeta] ?? item;

  return (
    <section data-testid="settings-llm-status">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="font-medium text-foreground">{t("settings.runtime")}</h2>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7 px-2"
          onClick={onRefresh}
          disabled={healthLoading}
        >
          {healthLoading ? "..." : t("settings.refresh")}
        </Button>
      </div>
      <div className="rounded-lg border border-border p-4 space-y-3">
        {health && statusMeta ? (
          <>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline">
                {t("settings.deployment")}:{" "}
                {health.deployment_mode === "single_user"
                  ? t("settings.singleUser")
                  : health.deployment_mode}
              </Badge>
              <Badge variant="outline">
                {t("settings.authMode")}:{" "}
                {health.auth_enabled
                  ? t("settings.authJwt")
                  : t("settings.authLocalOwner")}
              </Badge>
              <Badge
                variant={
                  health.migration_required ? "destructive" : "secondary"
                }
              >
                {t("settings.schema")}:{" "}
                {health.migration_required
                  ? t("settings.schemaMigrationRequired")
                  : t("settings.schemaReady")}
              </Badge>
              <Badge variant="outline">
                {t("settings.migrationStatus")}:{" "}
                {health.migration_status || t("settings.unknown")}
              </Badge>
              <Badge
                variant={
                  health.alembic_version_present ? "secondary" : "destructive"
                }
              >
                {health.alembic_version_present
                  ? t("settings.alembicTracked")
                  : t("settings.alembicMissing")}
              </Badge>
              <Badge variant="outline">
                {t("settings.sandbox")}: {health.code_sandbox_backend}/
                {health.code_sandbox_runtime}
              </Badge>
              <Badge
                variant={
                  health.code_sandbox_runtime_available
                    ? "secondary"
                    : "destructive"
                }
              >
                {health.code_sandbox_runtime_available
                  ? t("settings.sandboxReady")
                  : t("settings.sandboxUnavailable")}
              </Badge>
              <Badge variant="outline">
                {t("settings.databaseBackend")}:{" "}
                {databaseBackend === "sqlite"
                  ? t("settings.databaseBackendSqlite")
                  : databaseBackend}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {statusMeta.label}
              </span>
              <Badge variant={statusMeta.badgeVariant}>
                {health.llm_status}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {statusMeta.description}
            </p>
            {health.deployment_mode === "single_user" && (
              <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
                <p>{t("settings.singleUserNote")}</p>
                <p className="mt-2">{t("settings.localModeHelp")}</p>
              </div>
            )}
            {health.migration_required && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-muted-foreground">
                {t("settings.migrationHelp")}
              </div>
            )}
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline">
                {t("settings.llmRequiredBadge")}:{" "}
                {health.llm_required ? t("settings.yes") : t("settings.no")}
              </Badge>
              <Badge variant="outline">
                {t("settings.llmAvailableBadge")}:{" "}
                {health.llm_available ? t("settings.yes") : t("settings.no")}
              </Badge>
              <Badge variant="outline">
                {t("settings.primaryBadge")}:{" "}
                {health.llm_primary || t("settings.none")}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {health.llm_providers.length > 0 ? (
                health.llm_providers.map((item) => (
                  <Badge
                    key={item}
                    variant={
                      health.llm_provider_health[item]
                        ? "secondary"
                        : "destructive"
                    }
                  >
                    {item}:{" "}
                    {health.llm_provider_health[item]
                      ? t("settings.providerHealthy")
                      : t("settings.providerUnhealthy")}
                  </Badge>
                ))
              ) : (
                <span className="text-sm text-muted-foreground">
                  {t("settings.noProvidersConfigured")}
                </span>
              )}
            </div>
            <div className="rounded-md border border-border bg-muted/20 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-foreground">
                  {t("settings.localBetaTitle")}
                </p>
                <Badge
                  variant={health.local_beta_ready ? "secondary" : "destructive"}
                >
                  {health.local_beta_ready
                    ? t("settings.localBetaReady")
                    : t("settings.localBetaBlocked")}
                </Badge>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t("settings.localBetaDescription")}
              </p>
              {blockers.length > 0 ? (
                <div className="mt-3 space-y-1">
                  <p className="text-xs font-medium text-foreground">
                    {t("settings.localBetaBlockers")}
                  </p>
                  <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                    {blockers.map((item) => (
                      <li key={item}>
                        {getIssueLabel(item)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {warnings.length > 0 ? (
                <div className="mt-3 space-y-1">
                  <p className="text-xs font-medium text-foreground">
                    {t("settings.localBetaWarnings")}
                  </p>
                  <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                    {warnings.map((item) => (
                      <li key={item}>
                        {getIssueLabel(item)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("settings.runtimeUnavailable")}
          </p>
        )}
      </div>
    </section>
  );
}
