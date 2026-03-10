"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";
import {
  getHealthStatus,
  getLlmRuntimeConfig,
  type HealthStatus,
  type LlmRuntimeConfig,
} from "@/lib/api";
import type { ProviderName } from "./sections/types";
import {
  RuntimeStatusSection,
  ProviderConnectionsSection,
  OllamaSection,
  AppearanceSection,
  NotificationsSection,
  UsageSection,
  DataExportSection,
  TemplatesSection,
} from "./sections";
import { RuntimeAlert } from "@/components/shared/runtime-alert";

export default function SettingsPage() {
  const router = useRouter();
  const t = useT();

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState<LlmRuntimeConfig | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [savingRuntime, setSavingRuntime] = useState(false);
  const [provider, setProvider] = useState<ProviderName>("ollama");
  const [model, setModel] = useState("llama3.2:3b");
  const [llmRequired, setLlmRequired] = useState(false);
  const healthErrorShown = useRef(false);
  const runtimeErrorShown = useRef(false);

  const loadHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      setHealth(await getHealthStatus());
      healthErrorShown.current = false;
    } catch (error) {
      setHealth(null);
      if (!healthErrorShown.current) {
        toast.error(error instanceof Error ? error.message : t("settings.runtimeUnavailable"));
        healthErrorShown.current = true;
      }
    } finally {
      setHealthLoading(false);
    }
  }, [t]);

  const loadRuntimeConfig = useCallback(async () => {
    setRuntimeLoading(true);
    try {
      const config = await getLlmRuntimeConfig();
      setRuntimeConfig(config);
      setProvider((config.provider as ProviderName) || "ollama");
      setModel(config.model || "llama3.2:3b");
      setLlmRequired(config.llm_required);
      runtimeErrorShown.current = false;
    } catch (error) {
      setRuntimeConfig(null);
      if (!runtimeErrorShown.current) {
        toast.error(error instanceof Error ? error.message : t("settings.runtimeUnavailable"));
        runtimeErrorShown.current = true;
      }
    } finally {
      setRuntimeLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadHealth();
    void loadRuntimeConfig();
    const id = setInterval(() => void loadHealth(), 30_000);
    return () => clearInterval(id);
  }, [loadHealth, loadRuntimeConfig]);

  function handleRuntimeSaved(config: LlmRuntimeConfig): void {
    setRuntimeConfig(config);
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border/60 px-6 py-4 flex items-center gap-3 glass sticky top-0 z-10">
        <button
          type="button"
          onClick={() => router.push("/")}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          aria-label={t("settings.back")}
        >
          &larr; {t("settings.back")}
        </button>
        <h1 className="text-lg font-bold text-foreground">
          {t("nav.settings")}
        </h1>
      </header>

      <div className="max-w-4xl mx-auto p-6 md:p-10 space-y-8">
        <RuntimeAlert health={health} />

        <RuntimeStatusSection
          health={health}
          healthLoading={healthLoading}
          onRefresh={() => void loadHealth()}
        />

        <ProviderConnectionsSection
          runtimeConfig={runtimeConfig}
          runtimeLoading={runtimeLoading}
          provider={provider}
          model={model}
          llmRequired={llmRequired}
          savingRuntime={savingRuntime}
          onProviderChange={setProvider}
          onModelChange={setModel}
          onLlmRequiredToggle={() => setLlmRequired((value) => !value)}
          onRuntimeSaved={handleRuntimeSaved}
          onRefreshConfig={() => void loadRuntimeConfig()}
          onRefreshHealth={() => void loadHealth()}
          setSavingRuntime={setSavingRuntime}
        />

        <OllamaSection
          provider={provider}
          model={model}
          savingRuntime={savingRuntime}
          onProviderChange={setProvider}
          onModelChange={setModel}
          onRuntimeSaved={handleRuntimeSaved}
          onRefreshHealth={() => void loadHealth()}
          setSavingRuntime={setSavingRuntime}
        />

        <AppearanceSection />

        <NotificationsSection />

        <UsageSection />

        <DataExportSection />

        <TemplatesSection />
      </div>
    </div>
  );
}
