"use client";

import { useSetup } from "./use-setup";
import { SetupProgress } from "./setup-progress";
import { LlmCheckStep } from "./llm-check-step";
import { ContentStep } from "./content-step";
import { DiscoveryStep } from "./discovery-step";
import { CanvasLoginModal } from "../new/canvas-login-modal";

export default function SetupPage() {
  const s = useSetup();

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-xl flex flex-col gap-8">
        {/* Header */}
        <div className="flex flex-col items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">OpenTutor</h1>
          <SetupProgress currentStep={s.step} t={s.t} />
        </div>

        {/* Step content */}
        <div className="border border-border rounded-xl bg-card p-6">
          {s.step === "llm" && (
            <LlmCheckStep
              llmReady={s.llmReady}
              llmChecking={s.llmChecking}
              health={s.health}
              provider={s.llmProvider}
              onProviderChange={s.setLlmProvider}
              model={s.llmModel}
              onModelChange={s.setLlmModel}
              apiKey={s.llmApiKey}
              onApiKeyChange={s.setLlmApiKey}
              baseUrl={s.llmBaseUrl}
              onBaseUrlChange={s.setLlmBaseUrl}
              testing={s.llmTesting}
              testError={s.llmTestError}
              onTest={s.testAndSaveLlm}
              onSkip={() => s.setStep("content")}
              t={s.t}
            />
          )}

          {s.step === "content" && (
            <ContentStep
              projectName={s.projectName}
              onProjectNameChange={s.setProjectName}
              nameError={s.nameError}
              onValidateName={s.validateName}
              files={s.files}
              onFilesChange={s.setFiles}
              url={s.url}
              onUrlChange={s.setUrl}
              urlError={s.urlError}
              onValidateUrl={s.validateUrl}
              isCanvasDetected={s.isCanvasDetected}
              canvasSessionValid={s.canvasSessionValid}
              canvasAuthenticating={s.canvasLogging}
              onAuthCanvas={s.handleAuthCanvas}
              onStartLearning={s.startLearning}
              onSkip={s.skipContent}
              t={s.t}
            />
          )}

          {s.step === "discovery" && (
            <DiscoveryStep
              parseSteps={s.parseSteps}
              parseProgress={s.parseProgress}
              parseLogs={s.parseLogs}
              hasCompletedJob={s.hasCompletedJob}
              allJobsFailed={s.allJobsFailed}
              noSourcesSubmitted={s.noSourcesSubmitted}
              aiProbeResponse={s.aiProbeResponse}
              aiProbeStreaming={s.aiProbeStreaming}
              aiProbeDone={s.aiProbeDone}
              canEnterEarly={s.canEnterEarly}
              onEnterWorkspace={s.enterWorkspace}
              t={s.t}
            />
          )}
        </div>
      </div>

      {/* Canvas login modal */}
      {s.showCanvasLogin && (
        <CanvasLoginModal
          url={s.url}
          canvasLogging={s.canvasLogging}
          canvasLoginError={s.canvasLoginError}
          onClose={() => s.setShowCanvasLogin(false)}
          onRetry={s.handleAuthCanvas}
          t={s.t}
        />
      )}
    </div>
  );
}
