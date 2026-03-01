"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Bell, CheckCircle2, Eye, EyeOff, Globe, Moon, Palette, RefreshCw, Sun, Wrench } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { setLocale, getLocale, type Locale } from "@/lib/i18n";
import { useT } from "@/lib/i18n-context";
import {
  applyTemplate,
  getHealthStatus,
  getLlmRuntimeConfig,
  listTemplates,
  testLlmRuntimeConnection,
  updateLlmRuntimeConfig,
  type HealthStatus,
  type LlmConnectionTestResult,
  type LlmRuntimeConfig,
} from "@/lib/api";
import { PushSubscriptionManager } from "@/components/push-subscription-manager";
const PROVIDERS = ["openai", "anthropic", "deepseek", "openrouter", "gemini", "groq"] as const;

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

const LLM_STATUS_META = {
  ready: {
    label: "Ready",
    description: "A real LLM provider is configured and healthy.",
    icon: CheckCircle2,
    badgeVariant: "default" as const,
  },
  degraded: {
    label: "Model Issue",
    description: "A provider is configured, but the active provider is unhealthy or degraded.",
    icon: AlertTriangle,
    badgeVariant: "destructive" as const,
  },
  configuration_required: {
    label: "Configuration Required",
    description: "This app requires a real LLM provider, but no API key or local backend is configured.",
    icon: Wrench,
    badgeVariant: "destructive" as const,
  },
  mock_fallback: {
    label: "Fallback Mode",
    description: "No real LLM is configured. The app is running with local mock responses.",
    icon: AlertTriangle,
    badgeVariant: "secondary" as const,
  },
};

export default function SettingsPage() {
  const router = useRouter();
  const t = useT();
  const { theme, setTheme } = useTheme();
  const [locale, setLocaleState] = useState<Locale>("en");
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

  useEffect(() => {
    setLocaleState(getLocale());
    void Promise.all([loadTemplates(), loadHealth(), loadRuntimeConfig()]);
  }, []);

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

  const handleLocaleChange = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleState(newLocale);
    toast.success(newLocale === "zh" ? "已切换到中文" : "Switched to English");
  };

  const handleApplyTemplate = async (templateId: string) => {
    setApplying(templateId);
    try {
      await applyTemplate(templateId);
      toast.success("Template applied successfully");
    } catch {
      toast.error("Failed to apply template");
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
      toast.success("Saved local LLM configuration");
      await loadHealth();
    } catch (error) {
      toast.error((error as Error).message || "Failed to save LLM configuration");
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
      toast.success(`Deleted saved ${name} key`);
      await loadHealth();
    } catch (error) {
      toast.error((error as Error).message || `Failed to delete ${name} key`);
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
      toast.success(`${name} connection test passed`);
      await loadHealth();
    } catch (error) {
      setTestResults((prev) => ({ ...prev, [name]: null }));
      toast.error((error as Error).message || `Failed to test ${name} connection`);
    } finally {
      setTestingProvider(null);
    }
  };

  const statusMeta = health ? LLM_STATUS_META[health.llm_status] : null;
  const StatusIcon = statusMeta?.icon;
  const providerStatus = useMemo(() => {
    const byProvider = new Map(runtimeConfig?.providers.map((item) => [item.provider, item]));
    return PROVIDERS.map((name) => ({
      provider: name,
      status: byProvider.get(name),
    }));
  }, [runtimeConfig]);

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-3 flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold">{t("nav.settings")}</h1>
      </header>

      <div className="max-w-4xl mx-auto p-6 space-y-8">
        <section data-testid="settings-llm-status">
          <div className="flex items-center gap-2 mb-3">
            <Wrench className="h-4 w-4" />
            <h2 className="font-medium">AI Runtime</h2>
            <Button variant="ghost" size="sm" className="ml-auto h-7 px-2" onClick={() => void loadHealth()} disabled={healthLoading}>
              <RefreshCw className={`h-3.5 w-3.5 ${healthLoading ? "animate-spin" : ""}`} />
            </Button>
          </div>
          <div className="rounded-lg border p-4 space-y-3">
            {health && statusMeta && StatusIcon ? (
              <>
                <div className="flex items-center gap-2">
                  <StatusIcon className="h-4 w-4" />
                  <span className="text-sm font-medium">{statusMeta.label}</span>
                  <Badge variant={statusMeta.badgeVariant}>{health.llm_status}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{statusMeta.description}</p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="outline">LLM required: {health.llm_required ? "yes" : "no"}</Badge>
                  <Badge variant="outline">LLM available: {health.llm_available ? "yes" : "no"}</Badge>
                  <Badge variant="outline">Primary: {health.llm_primary || "none"}</Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  {health.llm_providers.length > 0 ? (
                    health.llm_providers.map((item) => (
                      <Badge key={item} variant={health.llm_provider_health[item] ? "secondary" : "destructive"}>
                        {item}: {health.llm_provider_health[item] ? "healthy" : "unhealthy"}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">No providers configured.</span>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Unable to load runtime health from the API server.
              </p>
            )}
          </div>
        </section>

        <section data-testid="settings-api-keys">
          <div className="flex items-center gap-2 mb-3">
            <Wrench className="h-4 w-4" />
            <h2 className="font-medium">Provider Connections</h2>
            <Button variant="ghost" size="sm" className="ml-auto h-7 px-2" onClick={() => void loadRuntimeConfig()} disabled={runtimeLoading}>
              <RefreshCw className={`h-3.5 w-3.5 ${runtimeLoading ? "animate-spin" : ""}`} />
            </Button>
          </div>
          <div className="rounded-xl border p-4 space-y-4">
            <p className="text-sm text-muted-foreground">
              Paste provider API keys here for local use. Keys are stored in <code>apps/api/.env</code> on this machine and the backend reloads the LLM registry after saving.
            </p>
            <div className="grid gap-4 md:grid-cols-[180px,1fr,auto] items-end">
              <label className="space-y-2 text-sm">
                <span className="font-medium">Primary provider</span>
                <select
                  data-testid="settings-llm-provider"
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value as ProviderName)}
                >
                  {PROVIDERS.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-2 text-sm">
                <span className="font-medium">Model</span>
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
                LLM required: {llmRequired ? "On" : "Off"}
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {providerStatus.map(({ provider: name, status }) => {
                const pendingValue = draftKeys[name] ?? "";
                const showing = showKeys[name] ?? false;
                const testResult = testResults[name];
                return (
                  <div key={name} className="rounded-lg border p-3 space-y-3" data-testid={`provider-card-${name}`}>
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium capitalize">{name}</div>
                        <div className="text-xs text-muted-foreground">
                          {status?.has_key ? `Saved: ${status.masked_key}` : "No key saved"}
                        </div>
                      </div>
                      {name === provider && <Badge variant="secondary">Primary</Badge>}
                    </div>
                    <div className="flex gap-2">
                      <Input
                        data-testid={`provider-key-${name}`}
                        type={showing ? "text" : "password"}
                        value={pendingValue}
                        onChange={(e) => setDraftKeys((prev) => ({ ...prev, [name]: e.target.value }))}
                        placeholder={`Paste ${name} API key`}
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        onClick={() => setShowKeys((prev) => ({ ...prev, [name]: !prev[name] }))}
                        aria-label={`toggle-${name}-visibility`}
                      >
                        {showing ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </Button>
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground gap-2">
                      <span>Leave blank to keep the saved key unchanged.</span>
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
                          {testingProvider === name ? "Testing..." : "Test Connection"}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() => setDraftKeys((prev) => ({ ...prev, [name]: "" }))}
                        >
                          Clear draft
                        </Button>
                        {status?.has_key && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-destructive"
                            data-testid={`delete-provider-key-${name}`}
                            onClick={() => setDeleteTarget(name)}
                            disabled={savingRuntime}
                          >
                            Delete saved
                          </Button>
                        )}
                      </div>
                    </div>
                    {testResult && (
                      <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs" data-testid={`provider-test-result-${name}`}>
                        <div className="font-medium">
                          {testResult.ok ? "Connection OK" : "Connection returned unexpected response"}
                        </div>
                        <div className="text-muted-foreground">
                          Model: {testResult.model} · Preview: {testResult.response_preview || "empty"}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setDraftKeys({})} disabled={savingRuntime}>
                Reset Draft
              </Button>
              <Button type="button" data-testid="settings-save-llm" onClick={() => void handleSaveRuntime()} disabled={savingRuntime}>
                {savingRuntime ? "Saving..." : "Save Local LLM Config"}
              </Button>
            </div>
          </div>
        </section>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <Globe className="h-4 w-4" />
            <h2 className="font-medium">{t("pref.language")}</h2>
          </div>
          <div className="flex gap-2">
            <Button variant={locale === "en" ? "default" : "outline"} size="sm" onClick={() => handleLocaleChange("en")}>
              English
            </Button>
            <Button variant={locale === "zh" ? "default" : "outline"} size="sm" onClick={() => handleLocaleChange("zh")}>
              中文
            </Button>
          </div>
        </section>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <Palette className="h-4 w-4" />
            <h2 className="font-medium">Appearance</h2>
          </div>
          <div className="flex gap-2">
            <Button variant={theme === "light" ? "default" : "outline"} size="sm" onClick={() => setTheme("light")}>
              <Sun className="h-3.5 w-3.5 mr-1" />
              Light
            </Button>
            <Button variant={theme === "dark" ? "default" : "outline"} size="sm" onClick={() => setTheme("dark")}>
              <Moon className="h-3.5 w-3.5 mr-1" />
              Dark
            </Button>
            <Button variant={theme === "system" ? "default" : "outline"} size="sm" onClick={() => setTheme("system")}>
              System
            </Button>
          </div>
        </section>

        <section data-testid="settings-notifications">
          <div className="flex items-center gap-2 mb-3">
            <Bell className="h-4 w-4" />
            <h2 className="font-medium">Notifications</h2>
          </div>
          <PushSubscriptionManager />
        </section>

        <section>
          <div className="flex items-center gap-2 mb-3">
            <Palette className="h-4 w-4" />
            <h2 className="font-medium">Learning Templates</h2>
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            Apply a template to set your learning preferences. You can always customize later.
          </p>
          <div className="grid gap-3">
            {templates.map((template) => (
              <div key={template.id} className="border rounded-lg p-4 flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm">{template.name}</span>
                    {template.is_builtin && <Badge variant="secondary" className="text-xs">Built-in</Badge>}
                  </div>
                  <p className="text-xs text-muted-foreground mb-2">{template.description}</p>
                  <div className="flex flex-wrap gap-1">
                    {template.tags?.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                    ))}
                  </div>
                </div>
                <Button size="sm" variant="outline" onClick={() => handleApplyTemplate(template.id)} disabled={applying === template.id}>
                  {applying === template.id ? <RefreshCw className="h-3 w-3 animate-spin" /> : "Apply"}
                </Button>
              </div>
            ))}
            {templates.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No templates available. They will be created on first server start.
              </p>
            )}
          </div>
        </section>
      </div>
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete saved API key?</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `This removes the saved ${deleteTarget} API key from local config. You can still keep an unsaved draft in the input field.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteTarget && void handleDeleteSavedKey(deleteTarget)}
              disabled={savingRuntime}
            >
              {savingRuntime ? "Deleting..." : "Delete saved key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
