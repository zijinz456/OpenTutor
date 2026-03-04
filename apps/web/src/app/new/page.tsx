"use client";

import { useNewProject } from "./use-new-project";
import { ModeSelectionStep } from "./mode-selection-step";
import { ContentUploadStep } from "./content-upload-step";
import { ParsingProgressStep } from "./parsing-progress-step";
import { FeatureConfigStep } from "./feature-config-step";
import { CanvasLoginModal } from "./canvas-login-modal";

export default function NewProjectPage() {
  const p = useNewProject();

  return (
    <div className="min-h-screen bg-background">
      {p.step === "mode" && (
        <ModeSelectionStep
          mode={p.mode}
          onModeChange={p.setMode}
          onContinue={() => p.setStep("upload")}
          onBack={() => p.router.push("/")}
          t={p.t}
        />
      )}

      {p.step === "upload" && (
        <ContentUploadStep
          mode={p.mode}
          projectName={p.projectName}
          onProjectNameChange={p.setProjectName}
          nameError={p.nameError}
          onValidateName={p.validateName}
          files={p.files}
          onFilesChange={p.setFiles}
          url={p.url}
          onUrlChange={p.setUrl}
          urlError={p.urlError}
          onValidateUrl={p.validateUrl}
          autoScrape={p.autoScrape}
          onAutoScrapeChange={p.setAutoScrape}
          isCanvasDetected={p.isCanvasDetected}
          canvasSessionValid={p.canvasSessionValid}
          onAddUrl={p.handleAddUrl}
          onBack={() => p.setStep("mode")}
          onStartParsing={p.startParsing}
          t={p.t}
        />
      )}

      {p.step === "parsing" && (
        <ParsingProgressStep
          projectName={p.projectName}
          url={p.url}
          files={p.files}
          parseSteps={p.parseSteps}
          parseProgress={p.parseProgress}
          parseLogs={p.parseLogs}
          canContinueToFeatures={p.canContinueToFeatures}
          allJobsFailed={p.allJobsFailed}
          createdCourseId={p.createdCourseId}
          onEnterWorkspace={p.enterWorkspace}
          onContinueToFeatures={() => p.setStep("features")}
          t={p.t}
        />
      )}

      {p.step === "features" && (
        <FeatureConfigStep
          projectName={p.projectName}
          features={p.features}
          onToggleFeature={p.toggleFeature}
          nlInput={p.nlInput}
          onNlInputChange={p.setNlInput}
          onBack={() => p.setStep("parsing")}
          onEnterWorkspace={p.enterWorkspace}
          t={p.t}
        />
      )}

      {p.showCanvasLogin && (
        <CanvasLoginModal
          url={p.url}
          canvasLogging={p.canvasLogging}
          canvasLoginError={p.canvasLoginError}
          onClose={() => p.setShowCanvasLogin(false)}
          onRetry={p.handleAddUrl}
          t={p.t}
        />
      )}
    </div>
  );
}
