"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { type Locale } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-context";
import {
  applyTemplate,
  getHealthStatus,
  getLlmRuntimeConfig,
  getNotificationSettings,
  getOllamaModels,
  listTemplates,
  testLlmRuntimeConnection,
  updateLlmRuntimeConfig,
  updateNotificationSettings,
  getUsageSummary,
  getExportSessionUrl,
  type HealthStatus,
  type LlmConnectionTestResult,
  type LlmRuntimeConfig,
  type NotificationSettings,
  type OllamaModel,
  type UsageSummary,
} from "@/lib/api";
import { useNotificationStore } from "@/store/notifications";
const PROVIDERS = ["openai", "anthropic", "deepseek", "openrouter", "gemini", "groq", "ollama", "lmstudio", "textgenwebui"] as const;

const PROVIDER_META = {
  openai: { requiresKey: true, defaultModel: "gpt-4o-mini" },
  anthropic: { requiresKey: true, defaultModel: "claude-sonnet-4-20250514" },
  deepseek: { requiresKey: true, defaultModel: "deepseek-chat" },
  openrouter: { requiresKey: true, defaultModel: "openai/gpt-4o-mini" },
  gemini: { requiresKey: true, defaultModel: "gemini-2.0-flash" },
  groq: { requiresKey: true, defaultModel: "llama-3.3-70b-versatile" },
  ollama: { requiresKey: false, defaultModel: "llama3.2:1b" },
  lmstudio: { requiresKey: false, defaultModel: "default" },
  textgenwebui: { requiresKey: false, defaultModel: "default" },
} as const;

type ProviderName = (typeof PROVIDERS)[number];

interface Template {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  target_audience: string;
  tags: string[];
  preferences: Record<string, string>;
}

function getLlmStatusMeta(t: (key: string) => string) {
  return {
    ready: {
      label: t("settings.status.ready"),
      description: t("settings.status.readyDesc"),
      badgeVariant: "default" as const,
    },
    degraded: {
      label: t("settings.status.degraded"),
      description: t("settings.status.degradedDesc"),
      badgeVariant: "destructive" as const,
    },
    configuration_required: {
      label: t("settings.status.configurationRequired"),
      description: t("settings.status.configurationRequiredDesc"),
      badgeVariant: "destructive" as const,
    },
    mock_fallback: {
      label: t("settings.status.mockFallback"),
      description: t("settings.status.mockFallbackDesc"),
      badgeVariant: "secondary" as const,
    },
  };
}

export default function SettingsPage() {
  const router = useRouter();
  const t = useT();
  const { locale, setLocale } = useLocale();
  const { theme, setTheme } = useTheme();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [applying, setApplying] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState<LlmRuntimeConfig | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [savingRuntime, setSavingRuntime] = useState(false);
  const [provider, setProvider] = useState<ProviderName>("openai");
  const [model, setModel] = useState("gpt-4o-mini");
  const [llmRequired, setLlmRequired] = useState(false);
  const [draftKeys, setDraftKeys] = useState<Record<string, string>>({});
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [deleteTarget, setDeleteTarget] = useState<ProviderName | null>(null);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, LlmConnectionTestResult | null>>({});
  const [keyErrors, setKeyErrors] = useState<Record<string, string | null>>({});
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings | null>(null);
  const [notificationChannels, setNotificationChannels] = useState("");
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationSaving, setNotificationSaving] = useState(false);
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [ollamaLoading, setOllamaLoading] = useState(false);
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("http://localhost:11434");
  const [ollamaMessage, setOllamaMessage] = useState<string | null>(null);
  const {
    pushSupported,
    pushPermission,
    isSubscribed,
    subscribing: pushBusy,
    error: pushError,
    checkSubscription,
    subscribe,
    unsubscribe,
  } = useNotificationStore();

  useEffect(() => {
    void Promise.all([
      loadTemplates(),
      loadHealth(),
      loadRuntimeConfig(),
      loadUsage(),
      loadNotificationSettings(),
    ]);
    void checkSubscription();
    // Poll health every 30s so status stays fresh
    const id = setInterval(() => void loadHealth(), 30_000);
    return () => clearInterval(id);
  }, [checkSubscription]);

  const loadTemplates = async () => {
    try {
      const data = await listTemplates();
      setTemplates(data as unknown as Template[]);
    } catch {
      // Templates may not be seeded yet
    }
  };

  const loadHealth = async () => {
    setHealthLoading(true);
    try {
      setHealth(await getHealthStatus());
    } catch {
      setHealth(null);
    } finally {
      setHealthLoading(false);
    }
  };

  const loadRuntimeConfig = async () => {
    setRuntimeLoading(true);
    try {
      const config = await getLlmRuntimeConfig();
      setRuntimeConfig(config);
      setProvider((config.provider as ProviderName) || "openai");
      setModel(config.model || "gpt-4o-mini");
      setLlmRequired(config.llm_required);
      setDraftKeys({});
    } catch {
      setRuntimeConfig(null);
    } finally {
      setRuntimeLoading(false);
    }
  };

  const loadUsage = async () => {
    setUsageLoading(true);
    try {
      setUsage(await getUsageSummary("month"));
    } catch {
      setUsage(null);
    } finally {
      setUsageLoading(false);
    }
  };

  const loadNotificationSettings = async () => {
    setNotificationLoading(true);
    try {
      const data = await getNotificationSettings();
      setNotificationSettings(data);
      setNotificationChannels(data.channels_enabled.join(", "));
    } catch {
      setNotificationSettings(null);
    } finally {
      setNotificationLoading(false);
    }
  };

  const loadOllama = async () => {
    setOllamaLoading(true);
    setOllamaMessage(null);
    try {
      const models = await getOllamaModels(ollamaBaseUrl);
      setOllamaModels(models);
      setOllamaMessage(models.length > 0 ? null : "Ollama is reachable, but no models are installed.");
    } catch (error) {
      setOllamaModels([]);
      setOllamaMessage((error as Error).message || "Unable to reach Ollama.");
    } finally {
      setOllamaLoading(false);
    }
  };

  const handleLocaleChange = (newLocale: Locale) => {
    const message = newLocale === "zh" ? t("settings.languageChanged.zh") : t("settings.languageChanged.en");
    setLocale(newLocale);
    toast.success(message);
  };

  const handleApplyTemplate = async (templateId: string) => {
    setApplying(templateId);
    try {
      await applyTemplate(templateId);
      toast.success(t("settings.templateApplied"));
    } catch {
      toast.error(t("settings.templateApplyFailed"));
    } finally {
      setApplying(null);
    }
  };

  const handleSaveRuntime = async () => {
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
      setRuntimeConfig(updated);
      setDraftKeys({});
      toast.success(t("settings.runtimeSaved"));
      await loadHealth();
    } catch (error) {
      toast.error((error as Error).message || t("settings.runtimeSaveFailed"));
    } finally {
      setSavingRuntime(false);
    }
  };

  const handleDeleteSavedKey = async (name: ProviderName) => {
    setSavingRuntime(true);
    try {
      const updated = await updateLlmRuntimeConfig({
        provider_keys: { [name]: "" },
      });
      setRuntimeConfig(updated);
      setDraftKeys((prev) => ({ ...prev, [name]: "" }));
      toast.success(t("settings.savedKeyDeleted"));
      await loadHealth();
    } catch (error) {
      toast.error((error as Error).message || t("settings.savedKeyDeleteFailed"));
    } finally {
      setSavingRuntime(false);
      setDeleteTarget(null);
    }
  };

  const handleTestConnection = async (name: ProviderName) => {
    setTestingProvider(name);
    try {
      const result = await testLlmRuntimeConnection({
        provider: name,
        model: name === provider ? model : undefined,
        api_key: draftKeys[name]?.trim() || undefined,
      });
      setTestResults((prev) => ({ ...prev, [name]: result }));
      toast.success(`${name} ${t("settings.connectionTestPassed")}`);
      await loadHealth();
    } catch (error) {
      setTestResults((prev) => ({ ...prev, [name]: null }));
      toast.error((error as Error).message || `${t("settings.connectionTestFailed")}: ${name}`);
    } finally {
      setTestingProvider(null);
    }
  };

  const handleSaveNotifications = async () => {
    if (!notificationSettings) return;
    setNotificationSaving(true);
    try {
      const channels = notificationChannels
        .split(",")
        .map((channel) => channel.trim())
        .filter(Boolean);
      const updated = await updateNotificationSettings({
        channels_enabled: channels,
        quiet_hours_start: notificationSettings.quiet_hours_start,
        quiet_hours_end: notificationSettings.quiet_hours_end,
        timezone: notificationSettings.timezone,
        max_notifications_per_hour: notificationSettings.max_notifications_per_hour,
        max_notifications_per_day: notificationSettings.max_notifications_per_day,
        escalation_enabled: notificationSettings.escalation_enabled,
        escalation_delay_hours: notificationSettings.escalation_delay_hours,
      });
      setNotificationSettings(updated);
      setNotificationChannels(updated.channels_enabled.join(", "));
      toast.success("Notification settings saved");
    } catch (error) {
      toast.error((error as Error).message || "Failed to save notification settings");
    } finally {
      setNotificationSaving(false);
    }
  };

  const handleUseOllamaModel = async (modelName: string) => {
    setSavingRuntime(true);
    try {
      const updated = await updateLlmRuntimeConfig({
        provider: "ollama",
        model: modelName,
        base_url: ollamaBaseUrl,
      });
      setRuntimeConfig(updated);
      setProvider("ollama");
      setModel(modelName);
      toast.success(`Switched runtime to Ollama (${modelName})`);
      await loadHealth();
    } catch (error) {
      toast.error((error as Error).message || "Failed to switch to Ollama");
    } finally {
      setSavingRuntime(false);
    }
  };

  const hasKeyErrors = Object.values(keyErrors).some((err) => err !== null);
  const llmStatusMeta = getLlmStatusMeta(t);
  const statusMeta = health ? llmStatusMeta[health.llm_status] : null;
  const providerStatus = useMemo(() => {
    const byProvider = new Map(runtimeConfig?.providers.map((item) => [item.provider, item]));
    return PROVIDERS.map((name) => ({
      provider: name,
      status: byProvider.get(name),
    }));
  }, [runtimeConfig]);

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <button
          type="button"
          onClick={() => router.push("/")}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          &larr; {t("settings.back")}
        </button>
        <h1 className="text-lg font-semibold text-foreground">{t("nav.settings")}</h1>
      </header>

      <div className="max-w-4xl mx-auto p-6 space-y-8">
        <section data-testid="settings-llm-status">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="font-medium text-foreground">{t("settings.runtime")}</h2>
            <Button variant="ghost" size="sm" className="ml-auto h-7 px-2" onClick={() => void loadHealth()} disabled={healthLoading}>
              {healthLoading ? "..." : t("settings.refresh")}
            </Button>
          </div>
          <div className="rounded-lg border border-border p-4 space-y-3">
            {health && statusMeta ? (
              <>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="outline">
                    {t("settings.deployment")}: {health.deployment_mode === "single_user" ? t("settings.singleUser") : health.deployment_mode}
                  </Badge>
                  <Badge variant={health.migration_required ? "destructive" : "secondary"}>
                    {t("settings.schema")}: {health.migration_required ? t("settings.schemaMigrationRequired") : t("settings.schemaReady")}
                  </Badge>
                  <Badge variant="outline">
                    {t("settings.migrationStatus")}: {health.migration_status || t("settings.unknown")}
                  </Badge>
                  <Badge variant={health.alembic_version_present ? "secondary" : "destructive"}>
                    {health.alembic_version_present ? t("settings.alembicTracked") : t("settings.alembicMissing")}
                  </Badge>
                  <Badge variant="outline">
                    {t("settings.sandbox")}: {health.code_sandbox_backend}/{health.code_sandbox_runtime}
                  </Badge>
                  <Badge variant={health.code_sandbox_runtime_available ? "secondary" : "destructive"}>
                    {health.code_sandbox_runtime_available ? t("settings.sandboxReady") : t("settings.sandboxUnavailable")}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{statusMeta.label}</span>
                  <Badge variant={statusMeta.badgeVariant}>{health.llm_status}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{statusMeta.description}</p>
                {health.deployment_mode === "single_user" && (
                  <div className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
                    {t("settings.singleUserNote")}
                  </div>
                )}
                {health.migration_required && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-muted-foreground">
                    {t("settings.migrationHelp")}
                  </div>
                )}
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="outline">{t("settings.llmRequiredBadge")}: {health.llm_required ? t("settings.yes") : t("settings.no")}</Badge>
                  <Badge variant="outline">{t("settings.llmAvailableBadge")}: {health.llm_available ? t("settings.yes") : t("settings.no")}</Badge>
                  <Badge variant="outline">{t("settings.primaryBadge")}: {health.llm_primary || t("settings.none")}</Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  {health.llm_providers.length > 0 ? (
                    health.llm_providers.map((item) => (
                      <Badge key={item} variant={health.llm_provider_health[item] ? "secondary" : "destructive"}>
                        {item}: {health.llm_provider_health[item] ? t("settings.providerHealthy") : t("settings.providerUnhealthy")}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">{t("settings.noProvidersConfigured")}</span>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("settings.runtimeUnavailable")}
              </p>
            )}
          </div>
        </section>

        <section data-testid="settings-api-keys">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="font-medium text-foreground">{t("settings.provider")}</h2>
            <Button variant="ghost" size="sm" className="ml-auto h-7 px-2" onClick={() => void loadRuntimeConfig()} disabled={runtimeLoading}>
              {runtimeLoading ? "..." : t("settings.refresh")}
            </Button>
          </div>
          <div className="rounded-xl border border-border p-4 space-y-4">
            <p className="text-sm text-muted-foreground">
              {t("settings.providerStorageHelp")}
            </p>
            <div className="grid gap-4 md:grid-cols-[180px,1fr,auto] items-end">
              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">{t("settings.primaryProvider")}</span>
                <select
                  data-testid="settings-llm-provider"
                  className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground"
                  value={provider}
                  onChange={(e) => {
                    const nextProvider = e.target.value as ProviderName;
                    setProvider(nextProvider);
                    if (!model.trim() || model === PROVIDER_META[provider].defaultModel) {
                      setModel(PROVIDER_META[nextProvider].defaultModel);
                    }
                  }}
                >
                  {PROVIDERS.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span className="font-medium text-foreground">{t("settings.model")}</span>
                <Input
                  data-testid="settings-llm-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="gpt-4o-mini"
                />
              </label>
              <Button
                type="button"
                variant={llmRequired ? "default" : "outline"}
                data-testid="settings-llm-required"
                onClick={() => setLlmRequired((value) => !value)}
              >
                {llmRequired ? t("settings.requiredOn") : t("settings.requiredOff")}
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {providerStatus.map(({ provider: name, status }) => {
                const pendingValue = draftKeys[name] ?? "";
                const showing = showKeys[name] ?? false;
                const testResult = testResults[name];
                const requiresKey = status?.requires_key ?? PROVIDER_META[name].requiresKey;
                return (
                  <div key={name} className="rounded-lg border border-border p-3 space-y-3" data-testid={`provider-card-${name}`}>
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium capitalize text-foreground">{name}</div>
                        <div className="text-xs text-muted-foreground">
                          {requiresKey
                            ? status?.has_key ? `${t("settings.savedKey")}: ${status.masked_key}` : t("settings.noKeySaved")
                            : t("settings.localEndpoint")}
                        </div>
                      </div>
                      {name === provider && <Badge variant="secondary">{t("settings.primary")}</Badge>}
                    </div>
                    {requiresKey ? (
                      <div className="space-y-1">
                        <div className="flex gap-2">
                          <Input
                            data-testid={`provider-key-${name}`}
                            type={showing ? "text" : "password"}
                            value={pendingValue}
                            onChange={(e) => {
                              const val = e.target.value;
                              setDraftKeys((prev) => ({ ...prev, [name]: val }));
                              if (val.trim().length > 0 && val.trim().length < 8) {
                                setKeyErrors((prev) => ({ ...prev, [name]: t("settings.apiKeyTooShort") }));
                              } else {
                                setKeyErrors((prev) => ({ ...prev, [name]: null }));
                              }
                            }}
                            placeholder={`${t("settings.pasteApiKey")} (${name})`}
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => setShowKeys((prev) => ({ ...prev, [name]: !prev[name] }))}
                            aria-label={`toggle-${name}-visibility`}
                          >
                            {showing ? t("settings.hide") : t("settings.show")}
                          </Button>
                        </div>
                        {keyErrors[name] && <p className="text-xs text-destructive mt-1">{keyErrors[name]}</p>}
                      </div>
                    ) : (
                      <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                        {t("settings.localProviderHelp")}
                      </div>
                    )}
                    <div className="flex items-center justify-between text-xs text-muted-foreground gap-2">
                      <span>{requiresKey ? t("settings.keepSavedKey") : t("settings.localTestHelp")}</span>
                      <div className="flex items-center gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          data-testid={`test-provider-key-${name}`}
                          onClick={() => void handleTestConnection(name)}
                          disabled={savingRuntime || testingProvider === name}
                        >
                          {testingProvider === name ? t("settings.testing") : t("settings.testConnection")}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => setDraftKeys((prev) => ({ ...prev, [name]: "" }))}
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
                            onClick={() => setDeleteTarget(name)}
                            disabled={savingRuntime}
                          >
                            {t("settings.deleteSaved")}
                          </Button>
                        )}
                      </div>
                    </div>
                    {testResult && (
                      <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs" data-testid={`provider-test-result-${name}`}>
                        <div className="font-medium text-foreground">
                          {testResult.ok ? t("settings.connectionOk") : t("settings.connectionUnexpected")}
                        </div>
                        <div className="text-muted-foreground">
                          {t("settings.model")}: {testResult.model} · {t("settings.preview")}: {testResult.response_preview || t("settings.previewEmpty")}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setDraftKeys({})} disabled={savingRuntime}>
                {t("settings.resetDraft")}
              </Button>
              <Button type="button" data-testid="settings-save-llm" onClick={() => void handleSaveRuntime()} disabled={savingRuntime || hasKeyErrors}>
                {savingRuntime ? t("settings.saving") : t("settings.saveLocalConfig")}
              </Button>
            </div>
          </div>
        </section>

        <section data-testid="settings-ollama-wizard">
          <h2 className="font-medium text-foreground mb-3">{t("settings.localAi")}</h2>
          <p className="text-sm text-muted-foreground mb-3">
            {t("settings.localAiDescription")}
          </p>
          <div className="rounded-xl border border-border p-4 space-y-4">
            <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
              <Input
                value={ollamaBaseUrl}
                onChange={(e) => setOllamaBaseUrl(e.target.value)}
                placeholder="http://localhost:11434"
              />
              <Button type="button" variant="outline" onClick={() => void loadOllama()} disabled={ollamaLoading}>
                {ollamaLoading ? "Checking..." : "Detect Models"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setProvider("ollama");
                  if (ollamaModels[0]?.name) setModel(ollamaModels[0].name);
                }}
              >
                Use Ollama
              </Button>
            </div>

            {ollamaMessage && (
              <p className="text-xs text-muted-foreground">{ollamaMessage}</p>
            )}

            {ollamaModels.length > 0 && (
              <div className="space-y-2">
                {ollamaModels.map((entry) => (
                  <div key={entry.name} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{entry.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {(entry.size / (1024 * 1024 * 1024)).toFixed(1)} GB · updated {new Date(entry.modified_at).toLocaleDateString()}
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant={provider === "ollama" && model === entry.name ? "default" : "outline"}
                      onClick={() => void handleUseOllamaModel(entry.name)}
                      disabled={savingRuntime}
                    >
                      {provider === "ollama" && model === entry.name ? "Selected" : "Use Model"}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section>
          <h2 className="font-medium text-foreground mb-3">{t("pref.language")}</h2>
          <div className="flex gap-2">
            <Button data-testid="settings-language-en" variant={locale === "en" ? "default" : "outline"} size="sm" onClick={() => handleLocaleChange("en")}>
              English
            </Button>
            <Button data-testid="settings-language-zh" variant={locale === "zh" ? "default" : "outline"} size="sm" onClick={() => handleLocaleChange("zh")}>
              中文
            </Button>
          </div>
        </section>

        <section>
          <h2 className="font-medium text-foreground mb-3">{t("settings.theme")}</h2>
          <div className="flex gap-2">
            <Button data-testid="settings-theme-light" variant={theme === "light" ? "default" : "outline"} size="sm" onClick={() => setTheme("light")}>
              {t("settings.appearance.light")}
            </Button>
            <Button data-testid="settings-theme-dark" variant={theme === "dark" ? "default" : "outline"} size="sm" onClick={() => setTheme("dark")}>
              {t("settings.appearance.dark")}
            </Button>
            <Button data-testid="settings-theme-system" variant={theme === "system" ? "default" : "outline"} size="sm" onClick={() => setTheme("system")}>
              {t("settings.appearance.system")}
            </Button>
          </div>
        </section>

        <section data-testid="settings-notifications">
          <h2 className="font-medium text-foreground mb-3">{t("settings.notifications")}</h2>
          <div className="rounded-xl border border-border p-4 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">Push supported: {pushSupported ? "yes" : "no"}</Badge>
              <Badge variant="outline">Permission: {pushPermission || "unknown"}</Badge>
              <Badge variant={isSubscribed ? "secondary" : "outline"}>
                {isSubscribed ? "Subscribed" : "Not subscribed"}
              </Badge>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" onClick={() => void checkSubscription()} disabled={pushBusy}>
                Refresh Browser Status
              </Button>
              <Button type="button" size="sm" onClick={() => void subscribe()} disabled={!pushSupported || pushBusy || isSubscribed}>
                {pushBusy && !isSubscribed ? "Working..." : "Enable Push"}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => void unsubscribe()} disabled={!isSubscribed || pushBusy}>
                Disable Push
              </Button>
            </div>

            {pushError && (
              <p className="text-xs text-destructive">{pushError}</p>
            )}

            {notificationLoading ? (
              <div className="h-4 w-36 rounded bg-muted animate-pulse" />
            ) : notificationSettings ? (
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Channels</span>
                  <Input
                    value={notificationChannels}
                    onChange={(e) => setNotificationChannels(e.target.value)}
                    placeholder="web_push, email"
                  />
                  <span className="block text-xs text-muted-foreground">
                    Comma-separated channel ids.
                  </span>
                </label>

                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Timezone</span>
                  <Input
                    value={notificationSettings.timezone}
                    onChange={(e) => setNotificationSettings((current) => current ? {
                      ...current,
                      timezone: e.target.value,
                    } : current)}
                  />
                </label>

                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Quiet hours start</span>
                  <Input
                    value={notificationSettings.quiet_hours_start || ""}
                    onChange={(e) => setNotificationSettings((current) => current ? {
                      ...current,
                      quiet_hours_start: e.target.value || null,
                    } : current)}
                    placeholder="22:00"
                  />
                </label>

                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Quiet hours end</span>
                  <Input
                    value={notificationSettings.quiet_hours_end || ""}
                    onChange={(e) => setNotificationSettings((current) => current ? {
                      ...current,
                      quiet_hours_end: e.target.value || null,
                    } : current)}
                    placeholder="07:00"
                  />
                </label>

                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Max notifications / hour</span>
                  <Input
                    type="number"
                    min="1"
                    max="100"
                    value={notificationSettings.max_notifications_per_hour}
                    onChange={(e) => setNotificationSettings((current) => current ? {
                      ...current,
                      max_notifications_per_hour: Number.parseInt(e.target.value, 10) || 1,
                    } : current)}
                  />
                </label>

                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Max notifications / day</span>
                  <Input
                    type="number"
                    min="1"
                    max="500"
                    value={notificationSettings.max_notifications_per_day}
                    onChange={(e) => setNotificationSettings((current) => current ? {
                      ...current,
                      max_notifications_per_day: Number.parseInt(e.target.value, 10) || 1,
                    } : current)}
                  />
                </label>

                <label className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Escalation delay (hours)</span>
                  <Input
                    type="number"
                    min="1"
                    max="48"
                    value={notificationSettings.escalation_delay_hours}
                    onChange={(e) => setNotificationSettings((current) => current ? {
                      ...current,
                      escalation_delay_hours: Number.parseInt(e.target.value, 10) || 1,
                    } : current)}
                  />
                </label>

                <div className="space-y-2 text-sm">
                  <span className="font-medium text-foreground">Escalation</span>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={notificationSettings.escalation_enabled ? "default" : "outline"}
                      onClick={() => setNotificationSettings((current) => current ? {
                        ...current,
                        escalation_enabled: true,
                      } : current)}
                    >
                      Enabled
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={!notificationSettings.escalation_enabled ? "default" : "outline"}
                      onClick={() => setNotificationSettings((current) => current ? {
                        ...current,
                        escalation_enabled: false,
                      } : current)}
                    >
                      Disabled
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Notification settings unavailable.</p>
            )}

            <div className="flex justify-end">
              <Button type="button" onClick={() => void handleSaveNotifications()} disabled={!notificationSettings || notificationSaving}>
                {notificationSaving ? "Saving..." : "Save Notification Settings"}
              </Button>
            </div>
          </div>
        </section>

        <section data-testid="settings-usage">
          <h2 className="font-medium text-foreground mb-3">{t("settings.usage")}</h2>
          <div className="rounded-lg border border-border p-4">
            {usageLoading ? (
              <div className="h-4 w-32 bg-muted animate-pulse rounded" />
            ) : usage ? (
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-2xl font-semibold text-foreground">${usage.total_cost_usd.toFixed(2)}</div>
                  <div className="text-xs text-muted-foreground">{t("settings.costMonth")}</div>
                </div>
                <div>
                  <div className="text-2xl font-semibold text-foreground">{((usage.total_input_tokens + usage.total_output_tokens) / 1000).toFixed(1)}k</div>
                  <div className="text-xs text-muted-foreground">{t("settings.tokens")}</div>
                </div>
                <div>
                  <div className="text-2xl font-semibold text-foreground">{usage.total_calls}</div>
                  <div className="text-xs text-muted-foreground">{t("settings.apiCalls")}</div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t("settings.usageUnavailable")}</p>
            )}
          </div>
        </section>

        <section data-testid="settings-export">
          <h2 className="font-medium text-foreground mb-3">{t("settings.export")}</h2>
          <p className="text-sm text-muted-foreground mb-3">
            {t("settings.exportDescription")}
          </p>
          <a href={getExportSessionUrl()} download>
            <Button variant="outline" size="sm">
              {t("settings.exportButton")}
            </Button>
          </a>
        </section>

        <section>
          <h2 className="font-medium text-foreground mb-3">{t("settings.templates")}</h2>
          <p className="text-sm text-muted-foreground mb-4">
            {t("settings.templatesDescription")}
          </p>
          <div className="grid gap-3">
            {templates.map((template) => (
              <div key={template.id} className="border border-border rounded-lg p-4 flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm text-foreground">{template.name}</span>
                    {template.is_builtin && <Badge variant="secondary" className="text-xs">{t("settings.builtin")}</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground mb-2">{template.description}</p>
                  <div className="flex flex-wrap gap-1">
                    {template.tags?.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                    ))}
                  </div>
                </div>
                <Button size="sm" variant="outline" onClick={() => handleApplyTemplate(template.id)} disabled={applying === template.id}>
                  {applying === template.id ? t("settings.applying") : t("settings.apply")}
                </Button>
              </div>
            ))}
            {templates.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t("settings.templatesEmpty")}
              </p>
            )}
          </div>
        </section>
      </div>
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.deleteKeyTitle")}</DialogTitle>
            <DialogDescription>
              {deleteTarget ? `${deleteTarget}. ${t("settings.deleteKeyDescription")}` : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button data-testid="settings-delete-key-cancel" variant="outline" onClick={() => setDeleteTarget(null)}>
              {t("general.cancel")}
            </Button>
            <Button
              data-testid="settings-delete-key-confirm"
              variant="destructive"
              onClick={() => deleteTarget && void handleDeleteSavedKey(deleteTarget)}
              disabled={savingRuntime}
            >
              {savingRuntime ? t("settings.deleting") : t("settings.deleteSavedKey")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
