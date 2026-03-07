"use client";

import { useNewProject } from "./use-new-project";
import { ContentUploadStep } from "./content-upload-step";
import { ParsingProgressStep } from "./parsing-progress-step";
import { CanvasLoginModal } from "./canvas-login-modal";

/**
 * Simplified "add another course" page for returning users.
 * Skips mode selection and feature config — goes straight to upload → parse → workspace.
 */
export default function NewProjectPage() {
  const p = useNewProject();

  return (
    <div className="min-h-screen bg-background">
      {(p.step === "mode" || p.step === "upload") && (
        <ContentUploadStep
          mode="both"
          learningMode={p.learningMode}
          onLearningModeChange={p.setLearningMode}
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
          onBack={() => p.router.push("/")}
          onStartParsing={p.startParsing}
          t={p.t}
        />
      )}

      {(p.step === "parsing" || p.step === "features") && (
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
          onContinueToFeatures={p.enterWorkspace}
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
