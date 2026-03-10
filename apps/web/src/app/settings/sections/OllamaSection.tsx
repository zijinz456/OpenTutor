"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useT } from "@/lib/i18n-context";
import { getOllamaModels, updateLlmRuntimeConfig } from "@/lib/api";
import type { LlmRuntimeConfig, OllamaModel, ProviderName } from "./types";

interface OllamaSectionProps {
  provider: ProviderName;
  model: string;
  savingRuntime: boolean;
  onProviderChange: (provider: ProviderName) => void;
  onModelChange: (model: string) => void;
  onRuntimeSaved: (config: LlmRuntimeConfig) => void;
  onRefreshHealth: () => void;
  setSavingRuntime: (saving: boolean) => void;
}

export function OllamaSection({
  provider,
  model,
  savingRuntime,
  onProviderChange,
  onModelChange,
  onRuntimeSaved,
  onRefreshHealth,
  setSavingRuntime,
}: OllamaSectionProps) {
  const t = useT();
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [ollamaLoading, setOllamaLoading] = useState(false);
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState(
    "http://localhost:11434",
  );
  const [ollamaMessage, setOllamaMessage] = useState<string | null>(null);

  async function loadOllama(): Promise<void> {
    setOllamaLoading(true);
    setOllamaMessage(null);
    try {
      const models = await getOllamaModels(ollamaBaseUrl);
      setOllamaModels(models);
      if (models.length === 0) {
        setOllamaMessage(
          "Ollama is reachable, but no models are installed.",
        );
      }
    } catch (error) {
      setOllamaModels([]);
      setOllamaMessage(
        (error as Error).message || "Unable to reach Ollama.",
      );
    } finally {
      setOllamaLoading(false);
    }
  }

  async function handleUseOllamaModel(modelName: string): Promise<void> {
    setSavingRuntime(true);
    try {
      const updated = await updateLlmRuntimeConfig({
        provider: "ollama",
        model: modelName,
        base_url: ollamaBaseUrl,
      });
      onRuntimeSaved(updated);
      onProviderChange("ollama");
      onModelChange(modelName);
      toast.success(`Switched runtime to Ollama (${modelName})`);
      await onRefreshHealth();
    } catch (error) {
      toast.error((error as Error).message || "Failed to switch to Ollama");
    } finally {
      setSavingRuntime(false);
    }
  }

  return (
    <section data-testid="settings-ollama-wizard">
      <h2 className="font-medium text-foreground mb-3">
        {t("settings.localAi")}
      </h2>
      <p className="text-sm text-muted-foreground mb-3">
        {t("settings.localAiDescription")}
      </p>
      <div className="rounded-xl border border-border p-4 space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
          <Input
            value={ollamaBaseUrl}
            onChange={(e) => setOllamaBaseUrl(e.target.value)}
            placeholder="http://localhost:11434"
            aria-label={t("settings.ollamaBaseUrl")}
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => void loadOllama()}
            disabled={ollamaLoading}
          >
            {ollamaLoading ? "Checking..." : "Detect Models"}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onProviderChange("ollama");
              if (ollamaModels[0]?.name) {
                onModelChange(ollamaModels[0].name);
              }
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
              <div
                key={entry.name}
                className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {entry.name}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {(entry.size / (1024 * 1024 * 1024)).toFixed(1)} GB
                    &middot; updated{" "}
                    {new Date(entry.modified_at).toLocaleDateString()}
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant={
                    provider === "ollama" && model === entry.name
                      ? "default"
                      : "outline"
                  }
                  onClick={() => void handleUseOllamaModel(entry.name)}
                  disabled={savingRuntime}
                >
                  {provider === "ollama" && model === entry.name
                    ? "Selected"
                    : "Use Model"}
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
