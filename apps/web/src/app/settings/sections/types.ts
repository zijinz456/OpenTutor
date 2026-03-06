import type {
  HealthStatus,
  LlmConnectionTestResult,
  LlmRuntimeConfig,
  OllamaModel,
  UsageSummary,
} from "@/lib/api";

export const PROVIDERS = [
  "ollama",
  "openai",
  "anthropic",
  "deepseek",
  "openrouter",
  "gemini",
  "groq",
  "lmstudio",
  "textgenwebui",
] as const;

export type ProviderName = (typeof PROVIDERS)[number];

export const PROVIDER_META: Record<
  ProviderName,
  { requiresKey: boolean; defaultModel: string }
> = {
  openai: { requiresKey: true, defaultModel: "gpt-4o-mini" },
  anthropic: { requiresKey: true, defaultModel: "claude-sonnet-4-20250514" },
  deepseek: { requiresKey: true, defaultModel: "deepseek-chat" },
  openrouter: { requiresKey: true, defaultModel: "openai/gpt-4o-mini" },
  gemini: { requiresKey: true, defaultModel: "gemini-2.0-flash" },
  groq: { requiresKey: true, defaultModel: "llama-3.3-70b-versatile" },
  ollama: { requiresKey: false, defaultModel: "llama3.2:3b" },
  lmstudio: { requiresKey: false, defaultModel: "default" },
  textgenwebui: { requiresKey: false, defaultModel: "default" },
};

export interface Template {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  target_audience: string;
  tags: string[];
  preferences: Record<string, string>;
}

export function getLlmStatusMeta(t: (key: string) => string) {
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

export function getLocalBetaIssueMeta(t: (key: string) => string) {
  return {
    database_unreachable: t("settings.localBeta.databaseUnreachable"),
    schema_not_ready: t("settings.localBeta.schemaNotReady"),
    llm_not_ready: t("settings.localBeta.llmNotReady"),
    llm_degraded: t("settings.localBeta.llmDegraded"),
    sandbox_runtime_unavailable: t("settings.localBeta.sandboxUnavailable"),
  } satisfies Record<string, string>;
}

export type {
  HealthStatus,
  LlmConnectionTestResult,
  LlmRuntimeConfig,
  OllamaModel,
  UsageSummary,
};
