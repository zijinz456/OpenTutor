"use client";

import { useCallback, useRef, useState } from "react";
import type { FileItem } from "../new/types";
import { formatSize } from "../new/types";

type ContentTab = "upload" | "url";

interface ContentStepProps {
  projectName: string;
  onProjectNameChange: (v: string) => void;
  nameError: string | null;
  onValidateName: (v: string) => void;
  files: FileItem[];
  onFilesChange: (f: FileItem[]) => void;
  url: string;
  onUrlChange: (v: string) => void;
  urlError: string | null;
  onValidateUrl: (v: string) => void;
  autoScrape: boolean;
  onAutoScrapeChange: (v: boolean) => void;
  isCanvasDetected: boolean;
  canvasSessionValid: boolean;
  canvasAuthenticating: boolean;
  onAuthCanvas: () => void;
  onQuickStart: () => void;
  quickStartLoading: boolean;
  onStartLearning: () => void;
  onSkip: () => void;
  onTryDemo: () => void;
  demoLoading: boolean;
  t: (key: string) => string;
}

export function ContentStep({
  projectName, onProjectNameChange, nameError, onValidateName,
  files, onFilesChange,
  url, onUrlChange, urlError, onValidateUrl,
  autoScrape, onAutoScrapeChange,
  isCanvasDetected, canvasSessionValid, canvasAuthenticating,
  onAuthCanvas, onQuickStart, quickStartLoading, onStartLearning, onSkip, onTryDemo, demoLoading, t,
}: ContentStepProps) {
  const [tab, setTab] = useState<ContentTab>("upload");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const hasContent = files.length > 0 || url.trim();
  const hasErrors = nameError !== null || urlError !== null;
  const needsCanvasAuth = isCanvasDetected && !canvasSessionValid;
  const canStart = projectName.trim() && hasContent && !hasErrors && !needsCanvasAuth && !canvasAuthenticating;

  function handleFileAdd(e: React.ChangeEvent<HTMLInputElement>): void {
    const selected = e.target.files;
    if (!selected) return;
    const newFiles = Array.from(selected).map((f) => ({
      file: f, name: f.name, size: formatSize(f.size),
    }));
    onFilesChange([...files, ...newFiles]);
    e.target.value = "";
  }

  function removeFile(idx: number): void {
    onFilesChange(files.filter((_, i) => i !== idx));
  }

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragging(true);
  }, []);
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragging(false);
  }, []);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragging(false);
    const dropped = e.dataTransfer.files;
    if (!dropped || dropped.length === 0) return;
    const newFiles = Array.from(dropped).map((f) => ({
      file: f, name: f.name, size: formatSize(f.size),
    }));
    onFilesChange([...files, ...newFiles]);
  }, [files, onFilesChange]);

  return (
    <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-3 duration-300">
      <div>
        <h3 className="text-lg font-semibold text-foreground">{t("setup.feedCourse")}</h3>
        <p className="text-sm text-muted-foreground mt-1">{t("setup.feedCourseDesc")}</p>
      </div>

      {/* Course Name */}
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium text-foreground">{t("new.projectName")}</label>
        <input
          data-testid="setup-course-name"
          className={`w-full h-10 px-3 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 ${nameError ? "border-destructive" : "border-border"}`}
          value={projectName}
          onChange={(e) => { onProjectNameChange(e.target.value); onValidateName(e.target.value); }}
          onBlur={() => onValidateName(projectName)}
          placeholder={t("new.projectNamePlaceholder")}
          maxLength={100}
        />
        {nameError && <p className="text-xs text-destructive">{nameError}</p>}
      </div>

      {/* Tab toggle */}
      <div className="flex border-b border-border">
        <button
          type="button"
          data-testid="setup-tab-upload"
          onClick={() => setTab("upload")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "upload"
              ? "border-brand text-brand"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {t("setup.uploadFiles")}
        </button>
        <button
          type="button"
          data-testid="setup-tab-url"
          onClick={() => setTab("url")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "url"
              ? "border-brand text-brand"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {t("setup.pasteUrl")}
        </button>
      </div>

      {/* Upload tab */}
      {tab === "upload" && (
        <div className="flex flex-col gap-3">
          <div
            data-testid="setup-dropzone"
            className={`w-full h-32 border-2 border-dashed rounded-lg flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors ${
              dragging
                ? "border-brand bg-brand-muted"
                : "border-border bg-muted hover:border-brand hover:bg-brand-muted"
            }`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragEnter={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <span className={`text-sm ${dragging ? "text-brand font-medium" : "text-muted-foreground"}`}>
              {dragging ? t("new.dropFiles") : t("new.dragFiles")}
            </span>
            <span className="text-xs text-muted-foreground">{t("new.supportedFormats")}</span>
          </div>
          <input
            ref={fileInputRef}
            data-testid="setup-file-input"
            type="file"
            accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
            multiple
            className="hidden"
            onChange={handleFileAdd}
          />
          {files.length > 0 && (
            <div className="flex flex-col gap-1.5">
              {files.map((f, idx) => (
                <div key={idx} className="flex items-center gap-3 px-3 py-2 bg-muted border border-border rounded-lg">
                  <span className="text-sm flex-1 text-foreground truncate">{f.name}</span>
                  <span className="text-xs text-muted-foreground">{f.size}</span>
                  <button type="button" onClick={() => removeFile(idx)} className="text-xs text-muted-foreground hover:text-foreground">
                    x
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* URL tab — simplified inline input with Canvas status */}
      {tab === "url" && (
        <div className="flex flex-col gap-3">
          <input
            data-testid="setup-url-input"
            className={`w-full h-10 px-3 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 ${urlError ? "border-destructive" : "border-border"}`}
            placeholder={t("new.urlPlaceholder")}
            value={url}
            onChange={(e) => { onUrlChange(e.target.value); onValidateUrl(e.target.value); }}
            onBlur={() => onValidateUrl(url)}
          />
          {urlError && <p className="text-xs text-destructive">{urlError}</p>}

          {/* Canvas detected: needs auth */}
          {isCanvasDetected && !canvasSessionValid && !urlError && (
            <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
              <span className="font-semibold">{t("new.canvasDetectedTitle")}</span>{" "}
              {t("new.canvasDetectedBody")}
              <button
                type="button"
                onClick={onAuthCanvas}
                disabled={canvasAuthenticating}
                className={`ml-2 px-3 py-0.5 rounded text-xs font-semibold text-brand-foreground ${
                  canvasAuthenticating ? "bg-brand/50 cursor-wait" : "bg-brand hover:opacity-90"
                }`}
              >
                {canvasAuthenticating ? t("setup.authenticating") : t("new.loginAndAdd")}
              </button>
            </div>
          )}

          {/* Canvas authenticated */}
          {isCanvasDetected && canvasSessionValid && !urlError && (
            <div className="p-3 px-4 bg-success-muted border border-success/30 rounded-md text-sm text-success leading-relaxed">
              <span className="font-semibold">{t("new.canvasAuthedTitle")}</span>{" "}
              {t("new.canvasAuthedBody")}
            </div>
          )}

          {/* Auto-scrape settings */}
          {url.trim() && !urlError && (
            <div className="flex flex-col gap-3 p-3 rounded-lg border border-border bg-muted/30">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  data-testid="setup-autoscrape-toggle"
                  title={t("new.autoscrapeToggle")}
                  aria-pressed={autoScrape ? "true" : "false"}
                  onClick={() => onAutoScrapeChange(!autoScrape)}
                  className={`w-10 h-5 rounded-full relative transition-colors shrink-0 ${autoScrape ? "bg-brand" : "bg-muted-foreground/30"}`}
                >
                  <div className={`w-4 h-4 bg-background rounded-full absolute top-[2px] transition-all ${autoScrape ? "right-[2px]" : "left-[2px]"}`} />
                </button>
                <div>
                  <span className="text-sm font-medium text-foreground">{t("new.autoscrapeToggle")}</span>
                  <p className="text-xs text-muted-foreground mt-0.5">{t("new.autoscrapeDesc")}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          onClick={onQuickStart}
          disabled={!canStart || quickStartLoading}
          data-testid="setup-quick-start"
          className={`h-10 px-6 rounded-lg text-sm font-semibold text-brand-foreground ${
            canStart && !quickStartLoading ? "bg-brand hover:opacity-90" : "bg-brand/50 cursor-not-allowed"
          }`}
        >
          {quickStartLoading ? t("setup.quickStartLoading") : t("setup.quickStart")}
        </button>
        <button
          type="button"
          onClick={onStartLearning}
          disabled={!canStart || quickStartLoading}
          data-testid="setup-start-learning"
          className="h-10 px-4 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {t("setup.startLearning")}
        </button>
        <button
          type="button"
          onClick={onSkip}
          className="h-10 px-4 text-sm text-muted-foreground hover:text-foreground"
        >
          {t("setup.skipContent")}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        {t("setup.quickStartHint")}
      </p>

      {/* Demo fast path */}
      <div className="flex items-center gap-3 pt-1">
        <div className="h-px flex-1 bg-border" />
        <span className="text-xs text-muted-foreground">{t("setup.orTryDemo")}</span>
        <div className="h-px flex-1 bg-border" />
      </div>
      <button
        type="button"
        onClick={onTryDemo}
        disabled={demoLoading}
        data-testid="setup-try-demo"
        className={`h-10 w-full rounded-lg text-sm font-medium border transition-colors ${
          demoLoading
            ? "border-border bg-muted text-muted-foreground cursor-wait"
            : "border-brand/30 bg-brand-muted text-brand hover:bg-brand/10"
        }`}
      >
        {demoLoading ? t("setup.loadingDemo") : t("setup.tryWithSample")}
      </button>
    </div>
  );
}
