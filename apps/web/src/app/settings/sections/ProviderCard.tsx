"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useT } from "@/lib/i18n-context";
import { PROVIDER_META, type LlmConnectionTestResult, type ProviderName } from "./types";

interface ProviderCardProps {
  name: ProviderName;
  isPrimary: boolean;
  status: { has_key?: boolean; masked_key?: string | null; requires_key?: boolean } | undefined;
  pendingValue: string;
  showing: boolean;
  testResult: LlmConnectionTestResult | null | undefined;
  keyError: string | null | undefined;
  savingRuntime: boolean;
  testingProvider: string | null;
  onDraftKeyChange: (name: ProviderName, value: string) => void;
  onToggleVisibility: (name: ProviderName) => void;
  onTestConnection: (name: ProviderName) => void;
  onClearDraft: (name: ProviderName) => void;
  onDeleteSaved: (name: ProviderName) => void;
  onKeyError: (name: ProviderName, error: string | null) => void;
}

export function ProviderCard({
  name,
  isPrimary,
  status,
  pendingValue,
  showing,
  testResult,
  keyError,
  savingRuntime,
  testingProvider,
  onDraftKeyChange,
  onToggleVisibility,
  onTestConnection,
  onClearDraft,
  onDeleteSaved,
  onKeyError,
}: ProviderCardProps) {
  const t = useT();
  const requiresKey = status?.requires_key ?? PROVIDER_META[name].requiresKey;

  function handleKeyChange(value: string): void {
    onDraftKeyChange(name, value);
    if (value.trim().length > 0 && value.trim().length < 8) {
      onKeyError(name, t("settings.apiKeyTooShort"));
    } else {
      onKeyError(name, null);
    }
  }

  return (
    <div
      className="rounded-lg border border-border p-3 space-y-3"
      data-testid={`provider-card-${name}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium capitalize text-foreground">
            {name}
          </div>
          <div className="text-xs text-muted-foreground">
            {requiresKey ? (
              status?.has_key ? (
                `${t("settings.savedKey")}: ${status.masked_key}`
              ) : (
                t("settings.noKeySaved")
              )
            ) : (
              t("settings.localEndpoint")
            )}
          </div>
        </div>
        {isPrimary && (
          <Badge variant="secondary">{t("settings.primary")}</Badge>
        )}
      </div>

      {requiresKey ? (
        <div className="space-y-1">
          <div className="flex gap-2">
            <Input
              data-testid={`provider-key-${name}`}
              type={showing ? "text" : "password"}
              value={pendingValue}
              onChange={(e) => handleKeyChange(e.target.value)}
              placeholder={`${t("settings.pasteApiKey")} (${name})`}
              aria-label={`${t("settings.pasteApiKey")} (${name})`}
              aria-required
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onToggleVisibility(name)}
              aria-label={`toggle-${name}-visibility`}
            >
              {showing ? t("settings.hide") : t("settings.show")}
            </Button>
          </div>
          {keyError && (
            <p className="text-xs text-destructive mt-1">{keyError}</p>
          )}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
          {t("settings.localProviderHelp")}
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-muted-foreground gap-2">
        <span>
          {requiresKey
            ? t("settings.keepSavedKey")
            : t("settings.localTestHelp")}
        </span>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2"
            data-testid={`test-provider-key-${name}`}
            onClick={() => onTestConnection(name)}
            disabled={savingRuntime || testingProvider === name}
          >
            {testingProvider === name
              ? t("settings.testing")
              : t("settings.testConnection")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2"
            onClick={() => onClearDraft(name)}
          >
            {t("settings.clearDraft")}
          </Button>
          {requiresKey && status?.has_key && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-destructive"
              data-testid={`delete-provider-key-${name}`}
              onClick={() => onDeleteSaved(name)}
              disabled={savingRuntime}
            >
              {t("settings.deleteSaved")}
            </Button>
          )}
        </div>
      </div>

      {testResult && (
        <div
          className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs"
          data-testid={`provider-test-result-${name}`}
        >
          <div className="font-medium text-foreground">
            {testResult.ok
              ? t("settings.connectionOk")
              : t("settings.connectionUnexpected")}
          </div>
          <div className="text-muted-foreground">
            {t("settings.model")}: {testResult.model} &middot;{" "}
            {t("settings.preview")}:{" "}
            {testResult.response_preview || t("settings.previewEmpty")}
          </div>
        </div>
      )}
    </div>
  );
}
