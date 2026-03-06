"use client";

import type { HealthStatus } from "@/lib/api";
import { PROVIDERS, PROVIDER_META, type ProviderName } from "../settings/sections/types";

const LOCAL_PROVIDERS = new Set(["ollama", "lmstudio", "textgenwebui"]);
const DEFAULT_BASE_URLS: Partial<Record<ProviderName, string>> = {
  ollama: "http://localhost:11434",
  lmstudio: "http://localhost:1234",
  textgenwebui: "http://localhost:5000",
};

interface LlmCheckStepProps {
  llmReady: boolean;
  llmChecking: boolean;
  health: HealthStatus | null;
  provider: string;
  onProviderChange: (v: string) => void;
  model: string;
  onModelChange: (v: string) => void;
  apiKey: string;
  onApiKeyChange: (v: string) => void;
  baseUrl: string;
  onBaseUrlChange: (v: string) => void;
  testing: boolean;
  testError: string | null;
  onTest: () => void;
  onSkip: () => void;
  t: (key: string) => string;
}

export function LlmCheckStep({
  llmReady, llmChecking, health,
  provider, onProviderChange,
  model, onModelChange,
  apiKey, onApiKeyChange,
  baseUrl, onBaseUrlChange,
  testing, testError, onTest, onSkip, t,
}: LlmCheckStepProps) {
  const prov = provider as ProviderName;
  const meta = PROVIDER_META[prov];
  const isLocal = LOCAL_PROVIDERS.has(provider);

  // Loading state
  if (llmChecking) {
    return (
      <div className="flex flex-col items-center gap-4 py-12 animate-in fade-in duration-300">
        <div className="w-10 h-10 border-3 border-brand border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-muted-foreground">{t("setup.checkingLlm")}</p>
      </div>
    );
  }

  // Already ready — show confirmation
  if (llmReady) {
    return (
      <div className="flex flex-col items-center gap-4 py-12 animate-in fade-in duration-300">
        <div className="w-14 h-14 rounded-full bg-success-muted flex items-center justify-center">
          <span className="text-2xl text-success">{"\u2713"}</span>
        </div>
        <div className="text-center">
          <h3 className="text-lg font-semibold text-foreground">{t("setup.llmConnected")}</h3>
          <p className="text-sm text-muted-foreground mt-1">
            {health?.llm_primary || `${provider} / ${model}`}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">{t("setup.autoAdvance")}</p>
      </div>
    );
  }

  // Config UI
  return (
    <div className="flex flex-col gap-5 animate-in fade-in slide-in-from-bottom-3 duration-300">
      <div>
        <h3 className="text-lg font-semibold text-foreground">{t("setup.connectLlm")}</h3>
        <p className="text-sm text-muted-foreground mt-1">{t("setup.connectLlmDesc")}</p>
      </div>

      {/* Provider */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-foreground">{t("setup.provider")}</label>
        <select
          value={provider}
          onChange={(e) => {
            const p = e.target.value as ProviderName;
            onProviderChange(p);
            onModelChange(PROVIDER_META[p]?.defaultModel || "");
            onBaseUrlChange(DEFAULT_BASE_URLS[p] || "");
            onApiKeyChange("");
          }}
          className="h-10 px-3 border border-border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20"
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      {/* Model */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-foreground">{t("setup.model")}</label>
        <input
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          placeholder={meta?.defaultModel || "model name"}
          className="h-10 px-3 border border-border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20"
        />
      </div>

      {/* API Key (for cloud providers) */}
      {meta?.requiresKey && (
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">{t("setup.apiKey")}</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => onApiKeyChange(e.target.value)}
            placeholder="sk-..."
            className="h-10 px-3 border border-border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20"
          />
        </div>
      )}

      {/* Base URL (for local providers) */}
      {isLocal && (
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-foreground">{t("setup.baseUrl")}</label>
          <input
            value={baseUrl}
            onChange={(e) => onBaseUrlChange(e.target.value)}
            placeholder={DEFAULT_BASE_URLS[prov] || "http://localhost:..."}
            className="h-10 px-3 border border-border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20"
          />
        </div>
      )}

      {testError && (
        <div className="p-3 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive">
          {testError}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={onTest}
          disabled={testing || !provider}
          className={`h-10 px-6 rounded-lg text-sm font-semibold text-brand-foreground ${
            testing ? "bg-brand/50 cursor-wait" : "bg-brand hover:opacity-90"
          }`}
        >
          {testing ? t("setup.testing") : t("setup.testConnection")}
        </button>
        <button
          onClick={onSkip}
          className="h-10 px-4 text-sm text-muted-foreground hover:text-foreground"
        >
          {t("setup.skipForNow")}
        </button>
      </div>
    </div>
  );
}
