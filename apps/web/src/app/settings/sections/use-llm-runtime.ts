"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";
import {
  getHealthStatus,
  getLlmRuntimeConfig,
  type HealthStatus,
  type LlmRuntimeConfig,
} from "@/lib/api";
import type { ProviderName } from "./types";

const DEFAULT_PROVIDER: ProviderName = "ollama";
const DEFAULT_MODEL = "llama3.2:3b";

/**
 * Runtime health + LLM provider configuration state shared by the settings
 * page and the first-run `/setup` gate. Returns everything
 * `ProviderConnectionsSection` needs as props.
 */
export function useLlmRuntime(options: { pollHealthMs?: number } = {}) {
  const { pollHealthMs = 30_000 } = options;
  const t = useT();

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthChecked, setHealthChecked] = useState(false);
  const [runtimeConfig, setRuntimeConfig] = useState<LlmRuntimeConfig | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [savingRuntime, setSavingRuntime] = useState(false);
  const [provider, setProvider] = useState<ProviderName>(DEFAULT_PROVIDER);
  const [model, setModel] = useState(DEFAULT_MODEL);
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
      setHealthChecked(true);
    }
  }, [t]);

  const loadRuntimeConfig = useCallback(async () => {
    setRuntimeLoading(true);
    try {
      const config = await getLlmRuntimeConfig();
      setRuntimeConfig(config);
      setProvider((config.provider as ProviderName) || DEFAULT_PROVIDER);
      setModel(config.model || DEFAULT_MODEL);
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
    if (!pollHealthMs) return;
    const id = setInterval(() => void loadHealth(), pollHealthMs);
    return () => clearInterval(id);
  }, [loadHealth, loadRuntimeConfig, pollHealthMs]);

  const llmReady = health?.llm_status === "ready";

  return {
    health,
    healthLoading,
    healthChecked,
    llmReady,
    loadHealth,
    runtimeConfig,
    runtimeLoading,
    loadRuntimeConfig,
    savingRuntime,
    setSavingRuntime,
    provider,
    setProvider,
    model,
    setModel,
    llmRequired,
    toggleLlmRequired: () => setLlmRequired((value) => !value),
    handleRuntimeSaved: (config: LlmRuntimeConfig) => setRuntimeConfig(config),
  };
}
