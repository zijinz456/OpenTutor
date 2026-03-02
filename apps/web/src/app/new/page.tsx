"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  IngestionJobSummary,
  createScrapeSource,
  listIngestionJobs,
  uploadFile,
  scrapeUrl,
  updateCourse,
  listAuthSessions,
  canvasBrowserLogin,
  type CourseMetadata,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { useCourseStore } from "@/store/course";

type Mode = "upload" | "url" | "both";
type Step = "mode" | "upload" | "parsing" | "features";

const STEP_LABELS: { key: Step; labelKey: string }[] = [
  { key: "mode", labelKey: "new.step.source" },
  { key: "upload", labelKey: "new.step.content" },
  { key: "parsing", labelKey: "new.step.parse" },
  { key: "features", labelKey: "new.step.features" },
];

/* Canvas URL detection — ported from learning-agent-extension */
const CANVAS_URL_PATTERNS = [
  /^https?:\/\/canvas\.[^/]*\.edu/i,
  /^https?:\/\/[^/]*\.edu\/.*canvas/i,
  /^https?:\/\/[^/]*\.instructure\.com/i,
  /^https?:\/\/[^/]*\.canvaslms\.com/i,
  /^https?:\/\/canvas\.lms\.[^/]+\.edu/i,
];

function isCanvasUrl(url: string): boolean {
  return CANVAS_URL_PATTERNS.some((p) => p.test(url));
}

interface FileItem {
  file: File;
  name: string;
  size: string;
}

interface ParseStep {
  label: string;
  status: "waiting" | "active" | "done";
}

const PARSE_STEPS: { key: string; labelKey: string }[] = [
  { key: "uploaded", labelKey: "new.parse.uploaded" },
  { key: "extracting", labelKey: "new.parse.extracting" },
  { key: "classifying", labelKey: "new.parse.classifying" },
  { key: "dispatching", labelKey: "new.parse.dispatching" },
  { key: "embedding", labelKey: "new.parse.embedding" },
];

const PHASE_ORDER = {
  uploaded: 0,
  extracting: 1,
  classifying: 2,
  dispatching: 3,
  embedding: 4,
  completed: 5,
  failed: 5,
} as const;

function getPhaseRank(status: string) {
  return PHASE_ORDER[status as keyof typeof PHASE_ORDER] ?? -1;
}

function deriveParseSteps(
  jobs: IngestionJobSummary[],
  isSubmittingContent: boolean,
  noSourcesSubmitted: boolean,
  t: (key: string) => string,
): ParseStep[] {
  if (noSourcesSubmitted) {
    return PARSE_STEPS.map((step) => ({ label: t(step.labelKey), status: "done" }));
  }
  if (!jobs.length) {
    return PARSE_STEPS.map((step, index) => ({
      label: t(step.labelKey),
      status: isSubmittingContent && index === 0 ? "active" : "waiting",
    }));
  }

  return PARSE_STEPS.map((step, index) => {
    const hasCurrent = jobs.some((job) => job.status === step.key);
    const hasReachedLater = jobs.some((job) => getPhaseRank(job.status) > index);
    const hasReachedCurrent = jobs.some((job) => getPhaseRank(job.status) >= index);

    let status: ParseStep["status"] = "waiting";
    if (hasCurrent) {
      status = "active";
    } else if (hasReachedLater || (hasReachedCurrent && jobs.every((job) => getPhaseRank(job.status) >= index || job.status === "failed"))) {
      status = "done";
    }
    return { label: t(step.labelKey), status };
  });
}

function deriveParseProgress(
  jobs: IngestionJobSummary[],
  isSubmittingContent: boolean,
  noSourcesSubmitted: boolean,
) {
  if (noSourcesSubmitted) return 100;
  if (!jobs.length) return isSubmittingContent ? 10 : 0;
  return Math.max(
    5,
    Math.min(
      100,
      Math.round(jobs.reduce((sum, job) => sum + (job.progress_percent ?? 0), 0) / jobs.length),
    ),
  );
}

const FEATURE_CARDS: { id: string; labelKey: string; descriptionKey: string; enabled: boolean; phase?: string }[] = [
  { id: "notes", labelKey: "new.notesFeature", descriptionKey: "new.notesFeatureDesc", enabled: true },
  { id: "practice", labelKey: "new.practiceFeature", descriptionKey: "new.practiceFeatureDesc", enabled: true },
  { id: "wrong_answer", labelKey: "new.reviewFeature", descriptionKey: "new.reviewFeatureDesc", enabled: true },
  { id: "study_plan", labelKey: "new.planFeature", descriptionKey: "new.planFeatureDesc", enabled: true },
  { id: "free_qa", labelKey: "new.qaFeature", descriptionKey: "new.qaFeatureDesc", enabled: true },
];

function StepIndicator({ currentStep, t }: { currentStep: Step; t: (key: string) => string }) {
  const currentIndex = STEP_LABELS.findIndex((s) => s.key === currentStep);
  return (
    <div className="flex items-center gap-2 text-xs">
      {STEP_LABELS.map((s, i) => (
        <span key={s.key} className="flex items-center gap-2">
          {i > 0 && <span className="text-muted-foreground">/</span>}
          <span
            className={
              i < currentIndex
                ? "text-brand font-medium"
                : i === currentIndex
                ? "text-foreground font-semibold"
                : "text-muted-foreground"
            }
          >
            {i + 1}. {t(s.labelKey)}
          </span>
        </span>
      ))}
    </div>
  );
}

export default function NewProjectPage() {
  const router = useRouter();
  const t = useT();
  const { addCourse, fetchContentTree } = useCourseStore();
  const [step, setStep] = useState<Step>("mode");
  const [mode, setMode] = useState<Mode>("both");
  const [projectName, setProjectName] = useState("");
  const [files, setFiles] = useState<FileItem[]>([]);
  const [url, setUrl] = useState("");
  const [autoScrape, setAutoScrape] = useState(true);
  const [features, setFeatures] = useState<Record<string, boolean>>({
    notes: true, practice: true, study_plan: true, free_qa: true, wrong_answer: true,
  });
  const [nlInput, setNlInput] = useState("");
  const [createdCourseId, setCreatedCourseId] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isCanvasDetected, setIsCanvasDetected] = useState(false);
  const [showCanvasLogin, setShowCanvasLogin] = useState(false);
  const [canvasLogging, setCanvasLogging] = useState(false);
  const [canvasLoginError, setCanvasLoginError] = useState<string | null>(null);
  const [canvasSessionValid, setCanvasSessionValid] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [ingestionJobs, setIngestionJobs] = useState<IngestionJobSummary[]>([]);
  const [isSubmittingContent, setIsSubmittingContent] = useState(false);
  const [noSourcesSubmitted, setNoSourcesSubmitted] = useState(false);
  const [parseLogs, setParseLogs] = useState<{ text: string; color: string }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const seenJobStatesRef = useRef<Record<string, string>>({});

  const parseSteps = deriveParseSteps(ingestionJobs, isSubmittingContent, noSourcesSubmitted, t);
  const parseProgress = deriveParseProgress(ingestionJobs, isSubmittingContent, noSourcesSubmitted);
  const hasCompletedJob = ingestionJobs.some((job) => job.status === "completed");
  const allJobsFailed = ingestionJobs.length > 0 && ingestionJobs.every((job) => job.status === "failed");
  const canContinueToFeatures = noSourcesSubmitted || hasCompletedJob;

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  };

  const validateName = (value: string) => {
    if (!value.trim()) {
      setNameError(t("new.projectNameRequired"));
    } else if (value.length > 100) {
      setNameError(t("new.projectNameTooLong"));
    } else {
      setNameError(null);
    }
  };

  const validateUrl = (value: string) => {
    const trimmed = value.trim();
    if (trimmed && !/^https?:\/\//i.test(trimmed)) {
      setUrlError(t("new.urlInvalid"));
    } else {
      setUrlError(null);
    }
    setIsCanvasDetected(trimmed ? isCanvasUrl(trimmed) : false);
  };

  const hasUploadErrors = nameError !== null || urlError !== null;

  const handleFileAdd = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected) return;
    const newFiles = Array.from(selected).map((f) => ({
      file: f,
      name: f.name,
      size: formatSize(f.size),
    }));
    setFiles((prev) => [...prev, ...newFiles]);
    e.target.value = "";
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const toggleFeature = (id: string) => {
    const card = FEATURE_CARDS.find((c) => c.id === id);
    if (card?.phase) return;
    setFeatures((prev) => ({ ...prev, [id]: !prev[id] }));
  };

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
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  useEffect(() => {
    if (step !== "parsing" || !createdCourseId || noSourcesSubmitted) {
      return;
    }

    let cancelled = false;

    const addLog = (text: string, color: string) => {
      setParseLogs((prev) => [...prev, { text, color }]);
    };

    const pollJobs = async () => {
      try {
        const jobs = await listIngestionJobs(createdCourseId);
        if (cancelled) return;

        setIngestionJobs(jobs);

        for (const job of jobs) {
          const stateKey = `${job.status}:${job.embedding_status}:${job.error_message ?? ""}`;
          if (seenJobStatesRef.current[job.id] === stateKey) {
            continue;
          }
          seenJobStatesRef.current[job.id] = stateKey;

          const label = job.filename || t("new.untitledSource");
          if (job.error_message) {
            addLog(`${new Date().toLocaleTimeString()}  ${label}: ${job.error_message}`, "text-destructive");
          } else if (job.phase_label) {
            addLog(`${new Date().toLocaleTimeString()}  ${label}: ${job.phase_label}`, "text-muted-foreground");
          }
        }
      } catch (error) {
        if (!cancelled) {
          addLog(
            `${new Date().toLocaleTimeString()}  ${t("new.logRefreshFailed")}: ${(error as Error).message}`,
            "text-destructive",
          );
        }
      }
    };

    void pollJobs();
    const timer = window.setInterval(() => {
      void pollJobs();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [createdCourseId, noSourcesSubmitted, step, t]);

  // Handle "Add" button click for URL input
  const handleAddUrl = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) return;

    if (!isCanvasUrl(trimmed)) {
      return;
    }

    try {
      const sessions = await listAuthSessions();
      const domain = new URL(trimmed).hostname;
      const match = sessions.find(
        (s) => s.is_valid && domain.includes(s.domain),
      );
      if (match) {
        setCanvasSessionValid(true);
        return;
      }
    } catch {
      // Auth session check failed — prompt login anyway
    }

    // No valid session — open browser login
    setCanvasLoginError(null);
    setShowCanvasLogin(true);
    setCanvasLogging(true);

    // Immediately call browser-login which opens a visible browser window
    try {
      await canvasBrowserLogin(trimmed);
      setCanvasSessionValid(true);
      setShowCanvasLogin(false);
    } catch (err) {
      setCanvasLoginError((err as Error).message || t("new.loginFailed"));
    } finally {
      setCanvasLogging(false);
    }
  }, [t, url]);

  // Start parsing: create course, upload files, scrape URL
  const startParsing = useCallback(async () => {
    setStep("parsing");
    setIngestionJobs([]);
    setParseLogs([]);
    setIsSubmittingContent(true);
    setNoSourcesSubmitted(false);
    seenJobStatesRef.current = {};

    const addLog = (text: string, color: string) => {
      setParseLogs((prev) => [...prev, { text, color }]);
    };
    let nextCourseId: string | null = null;

    try {
      const metadata: CourseMetadata = {
        workspace_features: features,
        auto_scrape: {
          enabled: Boolean(autoScrape && url.trim() && (mode === "url" || mode === "both")),
          interval_hours: 24,
        },
      };

      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logCreatingProject")} "${projectName || t("new.untitled")}"...`, "text-muted-foreground");
      const description = nlInput.trim() || undefined;
      const course = await addCourse(projectName.trim() || t("new.untitledProject"), description, metadata);
      nextCourseId = course.id;
      setCreatedCourseId(course.id);

      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logProjectCreated")}`, "text-success");
      const hasSources = files.length > 0 || (url.trim() && (mode === "url" || mode === "both"));
      if (!hasSources) {
        setNoSourcesSubmitted(true);
        addLog(
          `${new Date().toLocaleTimeString()}  ${t("new.logNoSources")}`,
          "text-muted-foreground",
        );
        return;
      }

      if (files.length > 0) {
        for (const f of files) {
          addLog(`${new Date().toLocaleTimeString()}  ${t("new.logUploading")} ${f.name}...`, "text-muted-foreground");
          try {
            const result = await uploadFile(course.id, f.file);
            addLog(
              `${new Date().toLocaleTimeString()}  ${f.name}: ${result.nodes_created} ${t("new.logNodesQueued")}`,
              "text-success",
            );
          } catch (err) {
            addLog(`${new Date().toLocaleTimeString()}  ${t("new.logFailed")}: ${f.name} — ${(err as Error).message}`, "text-destructive");
          }
        }
      }

      if (url.trim() && (mode === "url" || mode === "both")) {
        const urlIsCanvas = isCanvasUrl(url.trim());

        // Canvas URLs: ensure login before scraping
        if (urlIsCanvas && !canvasSessionValid) {
          addLog(
            `${new Date().toLocaleTimeString()}  ${t("new.logCanvasOpening")}`,
            "text-warning",
          );
          setShowCanvasLogin(true);
          setCanvasLogging(true);
          try {
            await canvasBrowserLogin(url.trim());
            setCanvasSessionValid(true);
            setShowCanvasLogin(false);
            addLog(
              `${new Date().toLocaleTimeString()}  ${t("new.logCanvasLoginSucceeded")}`,
              "text-success",
            );
          } catch (loginErr) {
            setCanvasLoginError((loginErr as Error).message || t("new.loginFailed"));
            setCanvasLogging(false);
            addLog(
              `${new Date().toLocaleTimeString()}  ${t("new.logCanvasLoginFailed")}: ${(loginErr as Error).message}`,
              "text-destructive",
            );
            addLog(
              `${new Date().toLocaleTimeString()}  ${t("new.logBrowserTip")}`,
              "text-warning",
            );
            return;
          } finally {
            setCanvasLogging(false);
          }
        }

        addLog(
          `${new Date().toLocaleTimeString()}  ${t("new.logFetching")} ${url}${urlIsCanvas ? ` (${t("new.logCanvasDetected")})` : ""}...`,
          "text-muted-foreground",
        );
        try {
          const result = await scrapeUrl(course.id, url.trim());
          addLog(
            `${new Date().toLocaleTimeString()}  ${t("new.logUrlAccepted")}: ${result.nodes_created} ${t("new.logNodesQueued")}`,
            "text-success",
          );
          if (autoScrape) {
            await createScrapeSource({
              course_id: course.id,
              url: url.trim(),
              label: projectName.trim() || t("new.untitledSource"),
              source_type: urlIsCanvas ? "canvas" : "generic",
              requires_auth: urlIsCanvas,
              interval_hours: 24,
            });
            addLog(
              `${new Date().toLocaleTimeString()}  ${t("new.logAutoScrapeEnabled")}`,
              "text-success",
            );
          }
        } catch (err) {
          const errMsg = (err as Error).message;
          addLog(`${new Date().toLocaleTimeString()}  ${t("new.logScrapeFailed")}: ${errMsg}`, "text-destructive");
          if (urlIsCanvas && errMsg.includes("authentication")) {
            addLog(
              `${new Date().toLocaleTimeString()}  ${t("new.logAuthTip")}`,
              "text-warning",
            );
          }
        }
      }
    } catch (err) {
      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logError")}: ${(err as Error).message}`, "text-destructive");
    } finally {
      setIsSubmittingContent(false);
      if (nextCourseId) {
        void fetchContentTree(nextCourseId).catch(() => undefined);
      }
    }
  }, [addCourse, autoScrape, canvasSessionValid, features, fetchContentTree, files, mode, nlInput, projectName, t, url]);

  const enterWorkspace = async () => {
    if (!createdCourseId) return;

    const metadata: CourseMetadata = {
      workspace_features: features,
      auto_scrape: {
        enabled: Boolean(autoScrape && url.trim() && (mode === "url" || mode === "both")),
        interval_hours: 24,
      },
    };

    try {
      await updateCourse(createdCourseId, { metadata });
    } catch {
      // The workspace still works even if metadata refresh fails
    }

    if (nlInput.trim()) {
      localStorage.setItem(`course_init_prompt_${createdCourseId}`, nlInput.trim());
    }

    router.push(`/course/${createdCourseId}`);
  };

  return (
    <div className="min-h-screen bg-background">
      {/* MODE SELECTION */}
      {step === "mode" && (
        <div className="h-screen flex items-center justify-center">
          <div className="w-[640px] flex flex-col gap-10 items-center animate-in fade-in duration-300">
            <div className="flex flex-col gap-3 items-center text-center">
              <StepIndicator currentStep="mode" t={t} />
              <h1 className="text-[32px] font-bold text-foreground mt-4">
                {t("new.mode.title")}
              </h1>
              <p className="text-[15px] text-muted-foreground max-w-[480px] leading-relaxed">
                {t("new.mode.subtitle")}
              </p>
            </div>

            <div className="flex gap-4 w-full">
              {([
                { key: "upload" as Mode, label: t("new.mode.upload"), desc: t("new.mode.uploadDesc") },
                { key: "url" as Mode, label: t("new.mode.url"), desc: t("new.mode.urlDesc") },
                { key: "both" as Mode, label: t("new.mode.both"), desc: t("new.mode.bothDesc") },
              ]).map((m) => (
                <button
                  type="button"
                  key={m.key}
                  onClick={() => setMode(m.key)}
                  data-testid={`mode-option-${m.key}`}
                  aria-pressed={mode === m.key}
                  data-selected={mode === m.key ? "true" : "false"}
                  className={`flex-1 flex flex-col items-center justify-center gap-3.5 p-7 rounded-[10px] transition-all ${
                    mode === m.key
                      ? "border-2 border-brand bg-brand-muted"
                      : "border border-border hover:border-foreground/20"
                  }`}
                >
                  <span className="font-semibold text-base text-foreground">
                    {m.label}
                  </span>
                  <span className="text-[13px] text-muted-foreground text-center leading-snug">{m.desc}</span>
                </button>
              ))}
            </div>

            <div className="flex justify-between w-full mt-2">
              <button
                type="button"
                data-testid="back-to-projects"
                onClick={() => router.push("/")}
                className="h-11 px-6 border border-border rounded-lg flex items-center gap-1.5 text-muted-foreground font-medium text-sm hover:border-foreground/20"
              >
                &larr; {t("new.backToProjects")}
              </button>
              <button
                type="button"
                onClick={() => setStep("upload")}
                data-testid="mode-continue"
                className="h-11 px-7 bg-brand text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm hover:opacity-90"
              >
                {t("new.continue")} &rarr;
              </button>
            </div>
          </div>
        </div>
      )}

      {/* UPLOAD FORM */}
      {step === "upload" && (
        <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
          {/* Top nav */}
          <div className="flex items-center gap-3">
            <button type="button" data-testid="new-back-mode" onClick={() => setStep("mode")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
              &larr; {t("settings.back")}
            </button>
            <div className="w-px h-4 bg-border" />
            <span className="font-semibold text-sm text-foreground">{t("new.createTitle")}</span>
            <div className="flex-1" />
            <StepIndicator currentStep="upload" t={t} />
          </div>

          <div className="flex items-center gap-2">
            <span className="px-2 py-1 bg-brand-muted text-brand text-[11px] font-medium rounded">
              {mode === "upload" ? t("new.mode.upload") : mode === "url" ? t("new.mode.url") : `${t("new.mode.both")}: ${t("new.mode.upload")} + ${t("new.addUrl")}`}
            </span>
          </div>

          {/* Project Name */}
          <div className="flex flex-col gap-2">
            <label className="font-semibold text-sm text-foreground">{t("new.projectName")}</label>
            <input
              data-testid="project-name-input"
              className={`w-full h-11 px-4 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand ${nameError ? "border-destructive" : "border-border"}`}
              value={projectName}
              onChange={(e) => {
                setProjectName(e.target.value);
                validateName(e.target.value);
              }}
              onBlur={() => validateName(projectName)}
              placeholder={t("new.projectNamePlaceholder")}
              maxLength={100}
            />
            {nameError && <p className="text-xs text-destructive mt-1">{nameError}</p>}
          </div>

          {/* Upload Section */}
          {(mode === "upload" || mode === "both") && (
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
                data-testid="project-file-input"
                type="file"
                accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
                multiple
                title={t("new.uploadTitle")}
                className="hidden"
                onChange={handleFileAdd}
              />
              {files.length > 0 && (
                <div className="flex flex-col gap-2">
                  {files.map((f, idx) => (
                    <div key={idx} className="flex items-center gap-3 px-4 py-2.5 bg-muted border border-border rounded-lg">
                      <span className="text-[13px] flex-1 text-foreground">{f.name}</span>
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

          {/* URL Section */}
          {(mode === "url" || mode === "both") && (
            <div className="flex flex-col gap-3">
              <h3 className="text-base font-semibold text-foreground">{t("new.addUrl")}</h3>
              <div className="flex gap-2">
                <input
                  data-testid="project-url-input"
                  className={`flex-1 h-11 px-4 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand ${urlError ? "border-destructive" : "border-border"}`}
                  placeholder={t("new.urlPlaceholder")}
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    validateUrl(e.target.value);
                  }}
                  onBlur={() => validateUrl(url)}
                />
                <button
                  type="button"
                  data-testid="add-url-button"
                  onClick={handleAddUrl}
                  className={`h-11 px-5 text-brand-foreground rounded-lg font-semibold text-sm ${
                    isCanvasDetected && !canvasSessionValid
                      ? "bg-warning hover:opacity-90"
                      : "bg-brand hover:opacity-90"
                  }`}
                >
                  {isCanvasDetected && !canvasSessionValid ? t("new.loginAndAdd") : t("new.add")}
                </button>
              </div>
              {urlError && <p className="text-xs text-destructive mt-1">{urlError}</p>}
              {isCanvasDetected && !urlError && canvasSessionValid && (
                <div className="p-3 px-4 bg-success-muted border border-success/30 rounded-md text-sm text-success leading-relaxed">
                  <span className="font-semibold">{t("new.canvasAuthedTitle")}</span>{" "}
                  {t("new.canvasAuthedBody")}
                </div>
              )}
              {isCanvasDetected && !urlError && !canvasSessionValid && (
                <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
                  <span className="font-semibold">{t("new.canvasDetectedTitle")}</span>{" "}
                  {t("new.canvasDetectedBody")}
                </div>
              )}
            </div>
          )}

          {/* Auto-Scrape Settings */}
          {(mode === "url" || mode === "both") && (
            <div className="flex flex-col gap-4">
              <h3 className="text-base font-semibold text-foreground">{t("new.autoscrapeTitle")}</h3>
              <p className="text-[13px] text-muted-foreground">{t("new.autoscrapeDesc")}</p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  data-testid="autoscrape-toggle"
                  title={t("new.autoscrapeToggle")}
                  aria-pressed={autoScrape}
                  onClick={() => setAutoScrape(!autoScrape)}
                  className={`w-11 h-6 rounded-full relative transition-colors ${autoScrape ? "bg-brand" : "bg-muted-foreground/30"}`}
                >
                  <div className={`w-[18px] h-[18px] bg-background rounded-full absolute top-[3px] transition-all ${autoScrape ? "right-[3px]" : "left-[3px]"}`} />
                </button>
                <span className="text-sm text-foreground">{t("new.autoscrapeToggle")}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">{t("new.frequency")}</span>
                <div className="flex items-center gap-2 px-3.5 h-10 border border-border rounded-md bg-background">
                  <span className="text-[13px] text-foreground">{t("new.every24h")}</span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-[18px] h-[18px] rounded-[3px] bg-brand flex items-center justify-center shrink-0">
                  <span className="text-[10px] text-brand-foreground font-bold">{"\u2713"}</span>
                </div>
                <span className="text-sm text-foreground">{t("new.remindExpiry")}</span>
              </div>
            </div>
          )}

          <div className="w-full h-px bg-border" />

          <div className="flex justify-end gap-4">
            <button type="button" data-testid="new-cancel-upload" onClick={() => setStep("mode")} className="h-11 px-6 border border-border rounded-lg text-muted-foreground font-medium text-sm hover:border-foreground/20">
              {t("new.cancel")}
            </button>
            <button
              type="button"
              onClick={startParsing}
              data-testid="start-parsing"
              disabled={hasUploadErrors}
              className={`h-11 px-7 text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm ${hasUploadErrors ? "bg-brand/50 cursor-not-allowed" : "bg-brand hover:opacity-90"}`}
            >
              {t("new.startParsing")} &rarr;
            </button>
          </div>
        </div>
      )}

      {/* PARSING PROGRESS */}
      {step === "parsing" && (
        <div className="h-screen flex flex-col animate-in fade-in duration-300">
          {/* Top bar */}
          <div className="h-12 px-6 bg-muted border-b border-border flex items-center gap-4 shrink-0">
            <span className="font-semibold text-sm text-foreground">
              {t("new.processingPrefix")} -- {projectName || t("new.newProject")}
            </span>
            <div className="flex-1" />
            <StepIndicator currentStep="parsing" t={t} />
            <div className={`flex items-center gap-1.5 px-2.5 h-6 rounded ${allJobsFailed ? "bg-destructive/10" : "bg-success-muted"}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${allJobsFailed ? "bg-destructive" : "bg-success"}`} />
              <span className={`text-[11px] font-semibold ${allJobsFailed ? "text-destructive" : "text-success"}`}>
                {allJobsFailed ? t("new.needsAttention") : t("new.active")}
              </span>
            </div>
          </div>

          <div className="flex flex-1 min-h-0">
            {/* Main content (left) */}
            <div className="flex-1 flex flex-col bg-background">
              {url && (
                <div className="h-9 px-4 bg-muted border-b border-border flex items-center gap-2">
                  <span className="text-xs text-muted-foreground flex-1 truncate">{url}</span>
                  {!canContinueToFeatures && <span className="text-xs text-muted-foreground animate-pulse">{t("new.loading")}</span>}
                </div>
              )}
              <div className="flex-1 p-6 bg-muted/50 flex flex-col gap-4 overflow-y-auto">
                <h2 className="text-xl font-bold text-foreground">{t("new.processingTitle")}</h2>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {t("new.processingDesc")}
                </p>
                {files.length > 0 && (
                  <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
                    {t("new.processingFiles")} {files.length} {t(files.length === 1 ? "new.fileCountOne" : "new.fileCountMany")}: {files.map((f) => f.name).join(", ")}
                  </div>
                )}
                {allJobsFailed && (
                  <div className="p-3 px-4 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive leading-relaxed">
                    {t("new.allJobsFailed")}
                  </div>
                )}
              </div>
            </div>

            {/* Parsing Sidebar (right) */}
            <div className="w-[340px] border-l border-border bg-background flex flex-col shrink-0">
              <div className="h-11 px-4 bg-muted border-b border-border flex items-center gap-2 shrink-0">
                {!canContinueToFeatures && <span className="text-xs text-brand animate-pulse">...</span>}
                <span className="font-semibold text-[13px] text-foreground">{t("new.parsingProgress")}</span>
              </div>
              <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto">
                <div className="flex flex-col gap-1.5">
                  <span className="font-semibold text-sm text-foreground">
                    {projectName || t("new.newProject")}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {files.length} {t(files.length === 1 ? "new.fileCountOne" : "new.fileCountMany")}{url ? ` + 1 ${t("new.urlSourceOne")}` : ""}
                  </span>
                </div>

                {/* Progress bar */}
                <div className="flex flex-col gap-1.5">
                  <div className="w-full h-1.5 bg-muted rounded-full">
                    <div
                      className="h-1.5 bg-brand rounded-full transition-all duration-500"
                      style={{ width: `${parseProgress}%` }}
                    />
                  </div>
                  <span className="text-xs font-medium text-brand">{parseProgress}% {t("new.completeSuffix")}</span>
                </div>

                {/* Steps */}
                <div className="flex flex-col gap-3">
                  {parseSteps.map((ps, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <div
                        className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${
                          ps.status === "done"
                            ? "bg-success"
                            : ps.status === "active"
                            ? "bg-brand"
                            : "border border-border"
                        }`}
                      >
                        {ps.status === "done" && <span className="text-[10px] text-success-foreground font-bold">{"\u2713"}</span>}
                        {ps.status === "active" && <span className="text-[10px] text-brand-foreground animate-pulse font-bold">...</span>}
                      </div>
                      <span
                        className={`text-xs ${
                          ps.status === "done"
                            ? "text-foreground font-medium"
                            : ps.status === "active"
                            ? "text-brand font-semibold"
                            : "text-muted-foreground"
                        }`}
                      >
                        {ps.label}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="w-full h-px bg-border" />

                {/* Processing Log */}
                <div className="flex flex-col gap-2">
                  <span className="text-xs font-semibold text-muted-foreground">{t("new.processingLog")}</span>
                  {parseLogs.map((log, idx) => (
                    <span key={idx} className={`text-[11px] font-mono ${log.color}`}>
                      {log.text}
                    </span>
                  ))}
                </div>

                <div className="flex-1" />

                <div className="flex flex-col gap-2">
                  {createdCourseId && (
                    <button
                      type="button"
                      onClick={enterWorkspace}
                      data-testid="enter-now"
                      className="w-full h-11 border border-border text-foreground rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:border-foreground/20"
                    >
                      {t("new.enterNow")}
                    </button>
                  )}
                  {canContinueToFeatures && (
                    <button
                      type="button"
                      onClick={() => setStep("features")}
                      data-testid="continue-to-features"
                      className="w-full h-11 bg-brand text-brand-foreground rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:opacity-90"
                    >
                      {t("new.continueToFeatures")} &rarr;
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* FEATURE SELECTION */}
      {step === "features" && (
        <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
          {/* Top nav */}
          <div className="flex items-center gap-3">
            <button type="button" data-testid="new-back-features" onClick={() => setStep("parsing")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
              &larr; {t("settings.back")}
            </button>
            <div className="w-px h-4 bg-border" />
            <span className="font-semibold text-sm text-foreground">
              {projectName || t("new.newProject")}
            </span>
            <div className="flex-1" />
            <StepIndicator currentStep="features" t={t} />
          </div>

          <div className="flex flex-col gap-2">
            <h1 className="text-[28px] font-bold text-foreground">
              {t("new.featureTitle")}
            </h1>
            <p className="text-[15px] text-muted-foreground">{t("new.featureSubtitle")}</p>
          </div>

          {/* Feature Cards -- 2-column grid */}
          <div className="grid grid-cols-2 gap-4">
            {FEATURE_CARDS.map((card) => (
              <button
                type="button"
                key={card.id}
                onClick={() => toggleFeature(card.id)}
                data-testid={`feature-card-${card.id}`}
                aria-pressed={features[card.id]}
                data-selected={features[card.id] ? "true" : "false"}
                className={`p-5 rounded-xl flex flex-col gap-3 text-left transition-all ${
                  features[card.id]
                    ? "border-2 border-brand"
                    : "border border-border"
                  } ${card.phase ? "opacity-60 cursor-default" : "hover:shadow-md"}`}
              >
                <div className="flex items-center gap-2.5 w-full">
                  <span className="font-semibold text-base text-foreground flex-1">
                    {t(card.labelKey)}
                  </span>
                  {card.phase && (
                    <span className="h-[22px] px-2 bg-warning-muted rounded text-[11px] font-semibold text-warning flex items-center">
                      {card.phase}
                    </span>
                  )}
                  <div
                    className={`w-[22px] h-[22px] rounded flex items-center justify-center shrink-0 ml-auto ${
                      features[card.id] ? "bg-brand" : "border-2 border-border"
                    }`}
                  >
                    {features[card.id] && <span className="text-[10px] text-brand-foreground font-bold">{"\u2713"}</span>}
                  </div>
                </div>
                <p className="text-[13px] text-muted-foreground">{t(card.descriptionKey)}</p>
              </button>
            ))}
          </div>

          {/* NL Input */}
          <div className="flex flex-col gap-2.5">
            <span className="font-semibold text-[15px] text-foreground">
              {t("new.extraPrompt")}
            </span>
            <textarea
              data-testid="new-extra-prompt"
              className="w-full h-20 p-3 border border-border rounded-lg bg-background resize-none text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
              placeholder={t("new.extraPromptPlaceholder")}
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
            />
          </div>

          <div className="w-full h-px bg-border" />

          <div className="flex justify-end gap-4">
            <button type="button" onClick={() => setStep("parsing")} className="h-11 px-6 border border-border rounded-lg text-muted-foreground font-medium text-sm hover:border-foreground/20">
              {t("settings.back")}
            </button>
            <button
              type="button"
              onClick={enterWorkspace}
              data-testid="enter-workspace"
              className="h-11 px-7 bg-brand text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm hover:opacity-90"
            >
              {t("new.enterWorkspace")} &rarr;
            </button>
          </div>
        </div>
      )}

      {/* Canvas Browser Login Modal */}
      {showCanvasLogin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[420px] bg-card rounded-xl shadow-2xl p-6 flex flex-col gap-5 animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-foreground">
                {t("new.canvasLogin")}
              </h2>
              {!canvasLogging && (
                <button
                  type="button"
                  onClick={() => setShowCanvasLogin(false)}
                  title={t("new.close")}
                  className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
                >
                  x
                </button>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">{t("new.canvasUrl")}</label>
              <div className="h-10 px-3 flex items-center border border-border rounded-lg bg-muted text-sm text-muted-foreground truncate">
                {url.trim()}
              </div>
            </div>

            {canvasLogging && (
              <div className="flex flex-col items-center gap-4 py-6">
                <div className="w-10 h-10 border-3 border-brand border-t-transparent rounded-full animate-spin" />
                <p className="text-sm font-medium text-foreground">
                  {t("new.canvasBrowserOpened")}
                </p>
                <p className="text-[13px] text-muted-foreground text-center leading-relaxed">
                  {t("new.canvasBrowserHelp")}
                </p>
              </div>
            )}

            {canvasLoginError && (
              <div className="p-3 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive">
                {canvasLoginError}
              </div>
            )}

            {!canvasLogging && canvasLoginError && (
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  data-testid="canvas-login-cancel"
                  onClick={() => setShowCanvasLogin(false)}
                  className="h-10 px-5 border border-border rounded-lg text-sm font-medium text-muted-foreground hover:border-foreground/20"
                >
                  {t("new.cancel")}
                </button>
                <button
                  type="button"
                  data-testid="canvas-login-retry"
                  onClick={handleAddUrl}
                  className="h-10 px-5 rounded-lg text-sm font-semibold text-brand-foreground bg-brand hover:opacity-90"
                >
                  {t("new.retry")}
                </button>
              </div>
            )}

            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {canvasLogging
                ? t("new.browserSessionNote")
                : t("new.loginTimeout")}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
