"use client";

import { useCallback, useRef, useState } from "react";
import { GraduationCap, Compass, Clock, Shield } from "lucide-react";
import type { Mode, FileItem } from "./types";
import type { LearningMode } from "@/lib/block-system/types";
import { formatSize } from "./types";
import { StepIndicator } from "./step-indicator";
import { UrlSection, AutoScrapeSection } from "./url-section";

interface ContentUploadStepProps {
  mode: Mode;
  learningMode: LearningMode;
  onLearningModeChange: (mode: LearningMode) => void;
  projectName: string;
  onProjectNameChange: (value: string) => void;
  nameError: string | null;
  onValidateName: (value: string) => void;
  files: FileItem[];
  onFilesChange: (files: FileItem[]) => void;
  url: string;
  onUrlChange: (value: string) => void;
  urlError: string | null;
  onValidateUrl: (value: string) => void;
  autoScrape: boolean;
  onAutoScrapeChange: (value: boolean) => void;
  isCanvasDetected: boolean;
  canvasSessionValid: boolean;
  onAddUrl: () => void;
  onBack: () => void;
  onStartParsing: () => void;
  t: (key: string) => string;
}

export function ContentUploadStep({
  mode,
  learningMode,
  onLearningModeChange,
  projectName,
  onProjectNameChange,
  nameError,
  onValidateName,
  files,
  onFilesChange,
  url,
  onUrlChange,
  urlError,
  onValidateUrl,
  autoScrape,
  onAutoScrapeChange,
  isCanvasDetected,
  canvasSessionValid,
  onAddUrl,
  onBack,
  onStartParsing,
  t,
}: ContentUploadStepProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const hasUploadErrors = nameError !== null || urlError !== null;

  function handleFileAdd(e: React.ChangeEvent<HTMLInputElement>): void {
    const selected = e.target.files;
    if (!selected) return;
    const newFiles = Array.from(selected).map((f) => ({
      file: f,
      name: f.name,
      size: formatSize(f.size),
    }));
    onFilesChange([...files, ...newFiles]);
    e.target.value = "";
  }

  function removeFile(idx: number): void {
    onFilesChange(files.filter((_, i) => i !== idx));
  }

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const droppedFiles = e.dataTransfer.files;
    if (!droppedFiles || droppedFiles.length === 0) return;
    const newFiles = Array.from(droppedFiles).map((f) => ({
      file: f,
      name: f.name,
      size: formatSize(f.size),
    }));
    onFilesChange([...files, ...newFiles]);
  }, [files, onFilesChange]);

  function getModeLabel(): string {
    if (mode === "upload") return t("new.mode.upload");
    if (mode === "url") return t("new.mode.url");
    return `${t("new.mode.both")}: ${t("new.mode.upload")} + ${t("new.addUrl")}`;
  }

  return (
    <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
      {/* Top nav */}
      <div className="flex items-center gap-3">
        <button type="button" data-testid="new-back-mode" onClick={onBack} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          &larr; {t("settings.back")}
        </button>
        <div className="w-px h-4 bg-border" />
        <span className="font-semibold text-sm text-foreground">{t("new.createTitle")}</span>
        <div className="flex-1" />
        <StepIndicator currentStep="upload" t={t} />
      </div>

      <div className="flex items-center gap-2">
        <span className="px-2 py-1 bg-brand-muted text-brand text-[11px] font-medium rounded">
          {getModeLabel()}
        </span>
      </div>

      {/* Project Name */}
      <div className="flex flex-col gap-2">
        <label className="font-semibold text-sm text-foreground">
          {t("new.projectName")}
          <span className="text-muted-foreground font-normal text-xs ml-1.5">{t("new.projectNameHint")}</span>
        </label>
        <input
          data-testid="project-name-input"
          className={`w-full h-11 px-4 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand ${nameError ? "border-destructive" : "border-border"}`}
          value={projectName}
          onChange={(e) => {
            onProjectNameChange(e.target.value);
            onValidateName(e.target.value);
          }}
          onBlur={() => onValidateName(projectName)}
          placeholder={t("new.projectNamePlaceholder")}
          maxLength={100}
        />
        {nameError && <p className="text-xs text-destructive mt-1">{nameError}</p>}
      </div>

      {/* Learning Mode */}
      <div className="flex flex-col gap-2">
        <label className="font-semibold text-sm text-foreground">
          {t("mode.title") !== "mode.title" ? t("mode.title") : "Learning Mode"}
        </label>
        <div className="grid grid-cols-2 gap-2">
          {(
            [
              { id: "course_following", icon: GraduationCap },
              { id: "self_paced", icon: Compass },
              { id: "exam_prep", icon: Clock },
              { id: "maintenance", icon: Shield },
            ] as const
          ).map((item) => {
            const Icon = item.icon;
            const active = learningMode === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onLearningModeChange(item.id)}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors ${
                  active
                    ? "border-brand bg-brand-muted/30 text-foreground"
                    : "border-border bg-card hover:border-brand/40"
                }`}
              >
                <Icon className={`size-3.5 ${active ? "text-brand" : "text-muted-foreground"}`} />
                <span className="text-xs font-medium">
                  {t(`mode.${item.id}`) !== `mode.${item.id}` ? t(`mode.${item.id}`) : item.id}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Upload Section */}
      {(mode === "upload" || mode === "both") && (
        <UploadSection
          files={files}
          dragging={dragging}
          fileInputRef={fileInputRef}
          onFileAdd={handleFileAdd}
          onRemoveFile={removeFile}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          t={t}
        />
      )}

      {/* URL Section */}
      {(mode === "url" || mode === "both") && (
        <UrlSection
          url={url}
          onUrlChange={onUrlChange}
          urlError={urlError}
          onValidateUrl={onValidateUrl}
          isCanvasDetected={isCanvasDetected}
          canvasSessionValid={canvasSessionValid}
          onAddUrl={onAddUrl}
          t={t}
        />
      )}

      {/* Auto-Scrape Settings */}
      {(mode === "url" || mode === "both") && (
        <AutoScrapeSection
          autoScrape={autoScrape}
          onAutoScrapeChange={onAutoScrapeChange}
          t={t}
        />
      )}

      <div className="w-full h-px bg-border" />

      <div className="flex justify-end gap-4">
        <button type="button" data-testid="new-cancel-upload" onClick={onBack} className="h-11 px-6 border border-border rounded-lg text-muted-foreground font-medium text-sm hover:border-foreground/20">
          {t("new.cancel")}
        </button>
        <button
          type="button"
          onClick={onStartParsing}
          data-testid="start-parsing"
          disabled={hasUploadErrors}
          className={`h-11 px-7 text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm ${hasUploadErrors ? "bg-brand/50 cursor-not-allowed" : "bg-brand hover:opacity-90"}`}
        >
          {t("new.startParsing")} &rarr;
        </button>
      </div>
    </div>
  );
}

/* ---------- Sub-sections ---------- */

interface UploadSectionProps {
  files: FileItem[];
  dragging: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  onFileAdd: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onRemoveFile: (idx: number) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  t: (key: string) => string;
}

function UploadSection({
  files,
  dragging,
  fileInputRef,
  onFileAdd,
  onRemoveFile,
  onDragOver,
  onDragLeave,
  onDrop,
  t,
}: UploadSectionProps) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-base font-semibold text-foreground">{t("new.uploadMaterials")}</h3>
      <div
        data-testid="upload-dropzone"
        className={`w-full h-40 border-2 border-dashed rounded-lg flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors ${
          dragging
            ? "border-brand bg-brand-muted"
            : "border-border bg-muted hover:border-brand hover:bg-brand-muted"
        }`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={onDragOver}
        onDragEnter={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <span className={`text-sm ${dragging ? "text-brand font-medium" : "text-muted-foreground"}`}>
          {dragging ? t("new.dropFiles") : t("new.dragFiles")}
        </span>
        <span className="text-xs text-muted-foreground">{t("new.supportedFormats")}</span>
      </div>
      <input
        ref={fileInputRef}
        data-testid="project-file-input"
        type="file"
        accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
        multiple
        title={t("new.uploadTitle")}
        className="hidden"
        onChange={onFileAdd}
      />
      {files.length > 0 && (
        <div className="flex flex-col gap-2">
          {files.map((f, idx) => (
            <div key={idx} className="flex items-center gap-3 px-4 py-2.5 bg-muted border border-border rounded-lg">
              <span className="text-[13px] flex-1 text-foreground">{f.name}</span>
              <span className="text-xs text-muted-foreground">{f.size}</span>
              <button type="button" onClick={() => onRemoveFile(idx)} className="text-xs text-muted-foreground hover:text-foreground">
                x
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
