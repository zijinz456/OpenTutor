"use client";

import { useRouter } from "next/navigation";
import { useT } from "@/lib/i18n-context";
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
import { useLlmRuntime } from "./sections/use-llm-runtime";
import { RuntimeAlert } from "@/components/shared/runtime-alert";

export default function SettingsPage() {
  const router = useRouter();
  const t = useT();
  const {
    health, healthLoading, loadHealth,
    runtimeConfig, runtimeLoading, loadRuntimeConfig,
    savingRuntime, setSavingRuntime,
    provider, setProvider, model, setModel,
    llmRequired, toggleLlmRequired, handleRuntimeSaved,
  } = useLlmRuntime();

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
          onLlmRequiredToggle={toggleLlmRequired}
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
