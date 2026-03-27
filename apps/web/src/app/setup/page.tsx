"use client";

import { Suspense } from "react";
import { useSetup } from "./use-setup";
import { SetupProgress } from "./setup-progress";
import { LlmCheckStep } from "./llm-check-step";
import { ContentStep } from "./content-step";
import { DiscoveryStep } from "./discovery-step";
import { TemplateStep } from "./template-step";
import { HabitInterviewStep } from "./habit-interview-step";
import { CanvasLoginModal } from "../new/canvas-login-modal";

function SetupInner() {
  const s = useSetup();

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-xl flex flex-col gap-8 animate-fade-in">
        {/* Header */}
        <div className="flex flex-col items-center gap-4">
          <div className="size-14 rounded-2xl bg-brand flex items-center justify-center shadow-md">
            <svg className="size-7 text-brand-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">OpenTutor</h1>
          <SetupProgress currentStep={s.step} t={s.t} />
        </div>

        {/* Step content */}
        <div className="rounded-2xl bg-card p-8 card-shadow">
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
              autoScrape={s.autoScrape}
              onAutoScrapeChange={s.setAutoScrape}
              isCanvasDetected={s.isCanvasDetected}
              canvasSessionValid={s.canvasSessionValid}
              canvasAuthenticating={s.canvasLogging}
              onAuthCanvas={s.handleAuthCanvas}
              onQuickStart={s.quickStart}
              quickStartLoading={s.quickStartLoading}
              onStartLearning={s.startLearning}
              onSkip={s.skipContent}
              onTryDemo={s.tryDemo}
              demoLoading={s.demoLoading}
              t={s.t}
            />
          )}

          {s.step === "interview" && (
            <HabitInterviewStep
              onComplete={s.acceptInterviewLayout}
              onSkip={s.skipInterview}
              onBack={() => s.setStep("content")}
              t={s.t}
            />
          )}

          {s.step === "template" && (
            <TemplateStep
              selectedTemplate={s.selectedTemplate}
              onSelect={s.setSelectedTemplate}
              selectedMode={s.selectedMode}
              onModeSelect={s.setSelectedMode}
              onConfirm={s.confirmTemplate}
              onBack={() => s.setStep("interview")}
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

export default function SetupPage() {
  return (
    <Suspense>
      <SetupInner />
    </Suspense>
  );
}
