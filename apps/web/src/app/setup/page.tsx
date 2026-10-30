"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useT } from "@/lib/i18n-context";
import { ProviderConnectionsSection } from "../settings/sections";
import { useLlmRuntime } from "../settings/sections/use-llm-runtime";

const ONBOARDED_KEY = "opentutor_onboarded";

function markOnboarded() {
  try { localStorage.setItem(ONBOARDED_KEY, "true"); } catch { /* quota */ }
}

/**
 * First-run gate: make sure an LLM is connected, then hand off to `/new`,
 * the single course-creation flow.
 */
export default function SetupPage() {
  const router = useRouter();
  const t = useT();
  const runtime = useLlmRuntime({ pollHealthMs: 0 });
  const autoAdvanced = useRef(false);

  const continueToNew = () => {
    markOnboarded();
    router.replace("/new");
  };

  // LLM already configured → go straight to course creation.
  useEffect(() => {
    if (autoAdvanced.current || !runtime.healthChecked || !runtime.llmReady) return;
    autoAdvanced.current = true;
    markOnboarded();
    router.replace("/new");
  }, [router, runtime.healthChecked, runtime.llmReady]);

  const checking = !runtime.healthChecked || runtime.llmReady;

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-3xl flex flex-col gap-8 animate-fade-in">
        <div className="flex flex-col items-center gap-4">
          <div className="size-14 rounded-2xl bg-brand flex items-center justify-center shadow-md">
            <svg className="size-7 text-brand-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
              <path d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">OpenTutor</h1>
        </div>

        <div className="rounded-2xl bg-card p-8 card-shadow">
          {checking ? (
            <div className="flex flex-col items-center gap-4 py-12" role="status" aria-live="polite">
              <div className="w-10 h-10 border-3 border-brand border-t-transparent rounded-full animate-spin" />
              <p className="text-sm text-muted-foreground">
                {runtime.llmReady ? t("setup.llmConnected") : t("setup.checkingLlm")}
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              <div>
                <h2 className="text-lg font-semibold text-foreground">{t("setup.connectLlm")}</h2>
                <p className="text-sm text-muted-foreground mt-1">{t("setup.connectLlmDesc")}</p>
              </div>

              <ProviderConnectionsSection
                runtimeConfig={runtime.runtimeConfig}
                runtimeLoading={runtime.runtimeLoading}
                provider={runtime.provider}
                model={runtime.model}
                llmRequired={runtime.llmRequired}
                savingRuntime={runtime.savingRuntime}
                onProviderChange={runtime.setProvider}
                onModelChange={runtime.setModel}
                onLlmRequiredToggle={runtime.toggleLlmRequired}
                onRuntimeSaved={runtime.handleRuntimeSaved}
                onRefreshConfig={() => void runtime.loadRuntimeConfig()}
                onRefreshHealth={() => void runtime.loadHealth()}
                setSavingRuntime={runtime.setSavingRuntime}
              />

              <div className="flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={continueToNew}
                  data-testid="setup-continue"
                  className="h-10 px-6 rounded-full text-sm font-semibold text-brand-foreground bg-brand hover:opacity-90"
                >
                  {t("setup.continueWithoutLlm")}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
