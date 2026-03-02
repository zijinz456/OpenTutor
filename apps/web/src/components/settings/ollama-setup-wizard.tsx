"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { getOllamaModels, updateLlmRuntimeConfig, type OllamaModel } from "@/lib/api";
import { toast } from "sonner";

type Step = "detect" | "select" | "confirm";

interface OllamaSetupWizardProps {
  onComplete?: () => void;
}

export function OllamaSetupWizard({ onComplete }: OllamaSetupWizardProps) {
  const [step, setStep] = useState<Step>("detect");
  const [baseUrl, setBaseUrl] = useState("http://localhost:11434");
  const [detecting, setDetecting] = useState(false);
  const [detected, setDetected] = useState<boolean | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [saving, setSaving] = useState(false);

  const handleDetect = async () => {
    setDetecting(true);
    setDetected(null);
    try {
      const result = await getOllamaModels(baseUrl);
      setModels(result);
      setDetected(true);
      if (result.length > 0) {
        setSelectedModel(result[0].name);
        setStep("select");
      }
    } catch {
      setDetected(false);
      setModels([]);
    } finally {
      setDetecting(false);
    }
  };

  const handleConfirm = async () => {
    if (!selectedModel) return;
    setSaving(true);
    try {
      await updateLlmRuntimeConfig({
        provider: "ollama",
        model: selectedModel,
        base_url: baseUrl,
      });
      toast.success(`Switched to Ollama (${selectedModel})`);
      setStep("confirm");
      onComplete?.();
    } catch (error) {
      toast.error((error as Error).message || "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "";
    const gb = bytes / 1_073_741_824;
    return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(bytes / 1_048_576).toFixed(0)} MB`;
  };

  return (
    <div className="rounded-lg border bg-card p-4 space-y-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className="text-primary" aria-hidden="true">Server</span>
        Ollama Setup
      </div>

      {/* Step 1: Detect */}
      <div className="space-y-2">
        <label className="text-xs text-muted-foreground">Ollama URL</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => { setBaseUrl(e.target.value); setDetected(null); }}
            className="flex-1 h-8 px-2 text-xs rounded-md border bg-background"
            placeholder="http://localhost:11434"
          />
          <Button size="sm" onClick={() => void handleDetect()} disabled={detecting}>
            {detecting ? <span className="animate-pulse">...</span> : "Detect"}
          </Button>
        </div>
        {detected === false && (
          <div className="flex items-center gap-1.5 text-xs text-red-600">
            <span aria-hidden="true">&#x2717;</span>
            <span>
              Cannot connect to Ollama. Make sure it&apos;s running.{" "}
              <a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer" className="underline">
                Install Ollama
              </a>
            </span>
          </div>
        )}
        {detected === true && models.length === 0 && (
          <div className="flex items-center gap-1.5 text-xs text-amber-600">
            <span aria-hidden="true">&#x2713;</span>
            <span>
              Ollama is running but no models found. Run{" "}
              <code className="bg-muted px-1 rounded">ollama pull llama3.2</code>{" "}
              to download a model.
            </span>
          </div>
        )}
      </div>

      {/* Step 2: Select model */}
      {step !== "detect" && models.length > 0 && (
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground">Select Model</label>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {models.map((m) => (
              <button
                key={m.name}
                type="button"
                onClick={() => setSelectedModel(m.name)}
                className={`w-full text-left px-3 py-2 rounded-md text-xs transition-colors ${
                  selectedModel === m.name
                    ? "bg-primary/10 text-primary border border-primary/30"
                    : "bg-muted/50 hover:bg-muted"
                }`}
              >
                <span className="font-medium">{m.name}</span>
                {m.size > 0 && <span className="ml-2 text-muted-foreground">{formatSize(m.size)}</span>}
              </button>
            ))}
          </div>
          {step === "select" && (
            <Button size="sm" onClick={() => void handleConfirm()} disabled={saving || !selectedModel}>
              {saving ? <span className="animate-pulse mr-1">...</span> : null}
              Activate Ollama
            </Button>
          )}
        </div>
      )}

      {/* Step 3: Confirmation */}
      {step === "confirm" && (
        <div className="flex items-center gap-1.5 text-xs text-green-600">
          <span aria-hidden="true">&#x2713;</span>
          <span>Ollama is now your active AI provider using <strong>{selectedModel}</strong>.</span>
        </div>
      )}
    </div>
  );
}
