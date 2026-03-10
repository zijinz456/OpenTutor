"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";
import {
  testLlmRuntimeConnection,
  updateLlmRuntimeConfig,
} from "@/lib/api";
import {
  PROVIDERS,
  PROVIDER_META,
  type LlmConnectionTestResult,
  type LlmRuntimeConfig,
  type ProviderName,
} from "./types";
import { ProviderCard } from "./ProviderCard";

interface ProviderConnectionsSectionProps {
  runtimeConfig: LlmRuntimeConfig | null;
  runtimeLoading: boolean;
  provider: ProviderName;
  model: string;
  llmRequired: boolean;
  savingRuntime: boolean;
  onProviderChange: (provider: ProviderName) => void;
  onModelChange: (model: string) => void;
  onLlmRequiredToggle: () => void;
  onRuntimeSaved: (config: LlmRuntimeConfig) => void;
  onRefreshConfig: () => void;
  onRefreshHealth: () => void;
  setSavingRuntime: (saving: boolean) => void;
}

export function ProviderConnectionsSection({
  runtimeConfig,
  runtimeLoading,
  provider,
  model,
  llmRequired,
  savingRuntime,
  onProviderChange,
  onModelChange,
  onLlmRequiredToggle,
  onRuntimeSaved,
  onRefreshConfig,
  onRefreshHealth,
  setSavingRuntime,
}: ProviderConnectionsSectionProps) {
  const t = useT();
  const [draftKeys, setDraftKeys] = useState<Record<string, string>>({});
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [deleteTarget, setDeleteTarget] = useState<ProviderName | null>(null);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, LlmConnectionTestResult | null>
  >({});
  const [keyErrors, setKeyErrors] = useState<Record<string, string | null>>({});

  const hasKeyErrors = Object.values(keyErrors).some((err) => err !== null);

  const providerStatus = useMemo(() => {
    const byProvider = new Map(
      runtimeConfig?.providers.map((item) => [item.provider, item]),
    );
    return PROVIDERS.map((name) => ({
      provider: name,
      status: byProvider.get(name),
    }));
  }, [runtimeConfig]);

  async function handleSaveRuntime(): Promise<void> {
    setSavingRuntime(true);
    try {
      const payloadKeys = Object.fromEntries(
        Object.entries(draftKeys).filter(([, value]) => value.trim().length > 0),
      );
      const updated = await updateLlmRuntimeConfig({
        provider,
        model,
        llm_required: llmRequired,
        provider_keys: payloadKeys,
      });
      onRuntimeSaved(updated);
      setDraftKeys({});
      toast.success(t("settings.runtimeSaved"));
      await onRefreshHealth();
    } catch (error) {
      toast.error(
        (error as Error).message || t("settings.runtimeSaveFailed"),
      );
    } finally {
      setSavingRuntime(false);
    }
  }

  async function handleDeleteSavedKey(name: ProviderName): Promise<void> {
    setSavingRuntime(true);
    try {
      const updated = await updateLlmRuntimeConfig({
        provider_keys: { [name]: "" },
      });
      onRuntimeSaved(updated);
      setDraftKeys((prev) => ({ ...prev, [name]: "" }));
      toast.success(t("settings.savedKeyDeleted"));
      await onRefreshHealth();
    } catch (error) {
      toast.error(
        (error as Error).message || t("settings.savedKeyDeleteFailed"),
      );
    } finally {
      setSavingRuntime(false);
      setDeleteTarget(null);
    }
  }

  async function handleTestConnection(name: ProviderName): Promise<void> {
    setTestingProvider(name);
    try {
      const result = await testLlmRuntimeConnection({
        provider: name,
        model: name === provider ? model : undefined,
        api_key: draftKeys[name]?.trim() || undefined,
      });
      setTestResults((prev) => ({ ...prev, [name]: result }));
      toast.success(`${name} ${t("settings.connectionTestPassed")}`);
      await onRefreshHealth();
    } catch (error) {
      setTestResults((prev) => ({ ...prev, [name]: null }));
      toast.error(
        (error as Error).message ||
          `${t("settings.connectionTestFailed")}: ${name}`,
      );
    } finally {
      setTestingProvider(null);
    }
  }

  function handleProviderSelectChange(nextProvider: ProviderName): void {
    onProviderChange(nextProvider);
    if (!model.trim() || model === PROVIDER_META[provider].defaultModel) {
      onModelChange(PROVIDER_META[nextProvider].defaultModel);
    }
  }

  return (
    <>
      <section data-testid="settings-api-keys">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="font-medium text-foreground">
            {t("settings.provider")}
          </h2>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto h-7 px-2"
            onClick={onRefreshConfig}
            disabled={runtimeLoading}
          >
            {runtimeLoading ? "..." : t("settings.refresh")}
          </Button>
        </div>
        <div className="rounded-xl border border-border p-4 space-y-4">
          <p className="text-sm text-muted-foreground">
            {t("settings.providerStorageHelp")}
          </p>
          <div className="grid gap-4 md:grid-cols-[180px,1fr,auto] items-end">
            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                {t("settings.primaryProvider")}
              </span>
              <select
                data-testid="settings-llm-provider"
                className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
                aria-required
                value={provider}
                onChange={(e) =>
                  handleProviderSelectChange(e.target.value as ProviderName)
                }
              >
                {PROVIDERS.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span className="font-medium text-foreground">
                {t("settings.model")}
              </span>
              <Input
                data-testid="settings-llm-model"
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
                placeholder="gpt-4o-mini"
                aria-required
              />
            </label>
            <Button
              type="button"
              variant={llmRequired ? "default" : "outline"}
              data-testid="settings-llm-required"
              onClick={onLlmRequiredToggle}
            >
              {llmRequired
                ? t("settings.requiredOn")
                : t("settings.requiredOff")}
            </Button>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {providerStatus.map(({ provider: name, status }) => (
              <ProviderCard
                key={name}
                name={name}
                isPrimary={name === provider}
                status={status}
                pendingValue={draftKeys[name] ?? ""}
                showing={showKeys[name] ?? false}
                testResult={testResults[name]}
                keyError={keyErrors[name]}
                savingRuntime={savingRuntime}
                testingProvider={testingProvider}
                onDraftKeyChange={(n, val) =>
                  setDraftKeys((prev) => ({ ...prev, [n]: val }))
                }
                onToggleVisibility={(n) =>
                  setShowKeys((prev) => ({ ...prev, [n]: !prev[n] }))
                }
                onTestConnection={(n) => void handleTestConnection(n)}
                onClearDraft={(n) =>
                  setDraftKeys((prev) => ({ ...prev, [n]: "" }))
                }
                onDeleteSaved={setDeleteTarget}
                onKeyError={(n, err) =>
                  setKeyErrors((prev) => ({ ...prev, [n]: err }))
                }
              />
            ))}
          </div>

          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setDraftKeys({})}
              disabled={savingRuntime}
            >
              {t("settings.resetDraft")}
            </Button>
            <Button
              type="button"
              data-testid="settings-save-llm"
              onClick={() => void handleSaveRuntime()}
              disabled={savingRuntime || hasKeyErrors}
            >
              {savingRuntime
                ? t("settings.saving")
                : t("settings.saveLocalConfig")}
            </Button>
          </div>
        </div>
      </section>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.deleteKeyTitle")}</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `${deleteTarget}. ${t("settings.deleteKeyDescription")}`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              data-testid="settings-delete-key-cancel"
              variant="outline"
              onClick={() => setDeleteTarget(null)}
            >
              {t("general.cancel")}
            </Button>
            <Button
              data-testid="settings-delete-key-confirm"
              variant="destructive"
              onClick={() =>
                deleteTarget && void handleDeleteSavedKey(deleteTarget)
              }
              disabled={savingRuntime}
            >
              {savingRuntime
                ? t("settings.deleting")
                : t("settings.deleteSavedKey")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
