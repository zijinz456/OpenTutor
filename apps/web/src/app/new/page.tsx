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
import { useCourseStore } from "@/store/course";

type Mode = "upload" | "url" | "both";
type Step = "mode" | "upload" | "parsing" | "features";

const STEP_LABELS: { key: Step; label: string }[] = [
  { key: "mode", label: "Source" },
  { key: "upload", label: "Content" },
  { key: "parsing", label: "Parse" },
  { key: "features", label: "Features" },
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

const PARSE_STEPS: { key: string; label: string }[] = [
  { key: "uploaded", label: "Uploads registered" },
  { key: "extracting", label: "Extracting content" },
  { key: "classifying", label: "Classifying materials" },
  { key: "dispatching", label: "Building workspace artifacts" },
  { key: "embedding", label: "Building semantic index" },
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
): ParseStep[] {
  if (noSourcesSubmitted) {
    return PARSE_STEPS.map((step) => ({ label: step.label, status: "done" }));
  }
  if (!jobs.length) {
    return PARSE_STEPS.map((step, index) => ({
      label: step.label,
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
    return { label: step.label, status };
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

const FEATURE_CARDS: { id: string; label: string; description: string; enabled: boolean; phase?: string }[] = [
  { id: "notes", label: "Organize Notes", description: "Restructure your materials into clean, organized notes in your preferred format.", enabled: true },
  { id: "practice", label: "Practice Mode", description: "Generate practice questions from your materials. Interactive Q&A with instant feedback.", enabled: true },
  { id: "wrong_answer", label: "Wrong Answer Review", description: "Track, diagnose, and revisit incorrect answers from generated quizzes.", enabled: true },
  { id: "study_plan", label: "Study Plan", description: "Generate a personalized study plan with scheduled reviews.", enabled: true },
  { id: "free_qa", label: "Free Q&A", description: "Ask any question about your materials and get AI-powered answers with source references.", enabled: true },
];

function StepIndicator({ currentStep }: { currentStep: Step }) {
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
            {i + 1}. {s.label}
          </span>
        </span>
      ))}
    </div>
  );
}

export default function NewProjectPage() {
  const router = useRouter();
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

  const parseSteps = deriveParseSteps(ingestionJobs, isSubmittingContent, noSourcesSubmitted);
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
      setNameError("Project name is required");
    } else if (value.length > 100) {
      setNameError("Project name must be 100 characters or fewer");
    } else {
      setNameError(null);
    }
  };

  const validateUrl = (value: string) => {
    const trimmed = value.trim();
    if (trimmed && !/^https?:\/\//i.test(trimmed)) {
      setUrlError("URL must start with http:// or https://");
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

          const label = job.filename || "Untitled source";
          if (job.error_message) {
            addLog(`${new Date().toLocaleTimeString()}  ${label}: ${job.error_message}`, "text-destructive");
          } else if (job.phase_label) {
            addLog(`${new Date().toLocaleTimeString()}  ${label}: ${job.phase_label}`, "text-muted-foreground");
          }
        }
      } catch (error) {
        if (!cancelled) {
          addLog(
            `${new Date().toLocaleTimeString()}  Failed to refresh ingestion status: ${(error as Error).message}`,
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
  }, [createdCourseId, noSourcesSubmitted, step]);

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
      setCanvasLoginError((err as Error).message || "Login failed or timed out");
    } finally {
      setCanvasLogging(false);
    }
  }, [url]);

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

      addLog(`${new Date().toLocaleTimeString()}  Creating project "${projectName || "Untitled"}"...`, "text-muted-foreground");
      const description = nlInput.trim() || undefined;
      const course = await addCourse(projectName.trim() || "Untitled Project", description, metadata);
      nextCourseId = course.id;
      setCreatedCourseId(course.id);

      addLog(`${new Date().toLocaleTimeString()}  Project created`, "text-success");
      const hasSources = files.length > 0 || (url.trim() && (mode === "url" || mode === "both"));
      if (!hasSources) {
        setNoSourcesSubmitted(true);
        addLog(
          `${new Date().toLocaleTimeString()}  No files or URLs submitted. You can continue and add content later.`,
          "text-muted-foreground",
        );
        return;
      }

      if (files.length > 0) {
        for (const f of files) {
          addLog(`${new Date().toLocaleTimeString()}  Uploading ${f.name}...`, "text-muted-foreground");
          try {
            const result = await uploadFile(course.id, f.file);
            addLog(
              `${new Date().toLocaleTimeString()}  ${f.name}: ${result.nodes_created} nodes queued`,
              "text-success",
            );
          } catch (err) {
            addLog(`${new Date().toLocaleTimeString()}  Failed: ${f.name} — ${(err as Error).message}`, "text-destructive");
          }
        }
      }

      if (url.trim() && (mode === "url" || mode === "both")) {
        const urlIsCanvas = isCanvasUrl(url.trim());
        addLog(
          `${new Date().toLocaleTimeString()}  Fetching ${url}${urlIsCanvas ? " (Canvas LMS detected)" : ""}...`,
          "text-muted-foreground",
        );
        try {
          const result = await scrapeUrl(course.id, url.trim());
          addLog(
            `${new Date().toLocaleTimeString()}  URL content accepted: ${result.nodes_created} nodes queued`,
            "text-success",
          );
          if (autoScrape) {
            await createScrapeSource({
              course_id: course.id,
              url: url.trim(),
              label: projectName.trim() || "Project source",
              source_type: urlIsCanvas ? "canvas" : "generic",
              requires_auth: urlIsCanvas,
              interval_hours: 24,
            });
            addLog(
              `${new Date().toLocaleTimeString()}  Auto-scrape enabled for this URL (every 24 hours)`,
              "text-success",
            );
          }
        } catch (err) {
          const errMsg = (err as Error).message;
          addLog(`${new Date().toLocaleTimeString()}  Scrape failed: ${errMsg}`, "text-destructive");
          if (urlIsCanvas && errMsg.includes("authentication")) {
            addLog(
              `${new Date().toLocaleTimeString()}  Tip: Go to Settings to authenticate, then retry.`,
              "text-warning",
            );
          }
        }
      }
    } catch (err) {
      addLog(`${new Date().toLocaleTimeString()}  Error: ${(err as Error).message}`, "text-destructive");
    } finally {
      setIsSubmittingContent(false);
      if (nextCourseId) {
        void fetchContentTree(nextCourseId).catch(() => undefined);
      }
    }
  }, [addCourse, autoScrape, features, fetchContentTree, files, mode, nlInput, projectName, url]);

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
              <StepIndicator currentStep="mode" />
              <h1 className="text-[32px] font-bold text-foreground mt-4">
                How would you like to add content?
              </h1>
              <p className="text-[15px] text-muted-foreground max-w-[480px] leading-relaxed">
                Choose how you want to bring learning materials into your new project.
              </p>
            </div>

            <div className="flex gap-4 w-full">
              {([
                { key: "upload" as Mode, label: "Upload Documents", desc: "Upload PDF, PPT, DOCX files from your computer" },
                { key: "url" as Mode, label: "Scrape from URL", desc: "Auto-fetch content from course websites and pages" },
                { key: "both" as Mode, label: "Both", desc: "Upload files and scrape URLs together" },
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
                onClick={() => router.push("/")}
                className="h-11 px-6 border border-border rounded-lg flex items-center gap-1.5 text-muted-foreground font-medium text-sm hover:border-foreground/20"
              >
                &larr; Back to Projects
              </button>
              <button
                type="button"
                onClick={() => setStep("upload")}
                data-testid="mode-continue"
                className="h-11 px-7 bg-brand text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm hover:opacity-90"
              >
                Continue &rarr;
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
            <button type="button" onClick={() => setStep("mode")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
              &larr; Back
            </button>
            <div className="w-px h-4 bg-border" />
            <span className="font-semibold text-sm text-foreground">Create New Project</span>
            <div className="flex-1" />
            <StepIndicator currentStep="upload" />
          </div>

          <div className="flex items-center gap-2">
            <span className="px-2 py-1 bg-brand-muted text-brand text-[11px] font-medium rounded">
              {mode === "upload" ? "Upload Documents" : mode === "url" ? "Scrape from URL" : "Both: Upload + URL"}
            </span>
          </div>

          {/* Project Name */}
          <div className="flex flex-col gap-2">
            <label className="font-semibold text-sm text-foreground">Project Name</label>
            <input
              data-testid="project-name-input"
              className={`w-full h-11 px-4 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand ${nameError ? "border-destructive" : "border-border"}`}
              value={projectName}
              onChange={(e) => {
                setProjectName(e.target.value);
                validateName(e.target.value);
              }}
              onBlur={() => validateName(projectName)}
              placeholder="CS101 Computer Science"
              maxLength={100}
            />
            {nameError && <p className="text-xs text-destructive mt-1">{nameError}</p>}
          </div>

          {/* Upload Section */}
          {(mode === "upload" || mode === "both") && (
            <div className="flex flex-col gap-3">
              <h3 className="text-base font-semibold text-foreground">Upload Learning Materials</h3>
              <div
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
                  {dragging ? "Drop files here" : "Drag files here, or click to browse"}
                </span>
                <span className="text-xs text-muted-foreground">Supports PDF, PPT, DOCX</span>
              </div>
              <input
                ref={fileInputRef}
                data-testid="project-file-input"
                type="file"
                accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
                multiple
                title="Upload learning materials"
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
              <h3 className="text-base font-semibold text-foreground">Add URL</h3>
              <div className="flex gap-2">
                <input
                  className={`flex-1 h-11 px-4 border rounded-lg bg-background text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand ${urlError ? "border-destructive" : "border-border"}`}
                  placeholder="https://professor-site.edu/cs101/"
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    validateUrl(e.target.value);
                  }}
                  onBlur={() => validateUrl(url)}
                />
                <button
                  type="button"
                  onClick={handleAddUrl}
                  className={`h-11 px-5 text-brand-foreground rounded-lg font-semibold text-sm ${
                    isCanvasDetected && !canvasSessionValid
                      ? "bg-warning hover:opacity-90"
                      : "bg-brand hover:opacity-90"
                  }`}
                >
                  {isCanvasDetected && !canvasSessionValid ? "Login & Add" : "Add"}
                </button>
              </div>
              {urlError && <p className="text-xs text-destructive mt-1">{urlError}</p>}
              {isCanvasDetected && !urlError && canvasSessionValid && (
                <div className="p-3 px-4 bg-success-muted border border-success/30 rounded-md text-sm text-success leading-relaxed">
                  <span className="font-semibold">Canvas LMS -- authenticated.</span>{" "}
                  Your Canvas session is active. Content will be fetched with your credentials.
                </div>
              )}
              {isCanvasDetected && !urlError && !canvasSessionValid && (
                <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
                  <span className="font-semibold">Canvas LMS detected.</span>{" "}
                  This URL requires authentication. Click <span className="font-medium">&quot;Login &amp; Add&quot;</span> to sign in with your university credentials.
                </div>
              )}
            </div>
          )}

          {/* Auto-Scrape Settings */}
          {(mode === "url" || mode === "both") && (
            <div className="flex flex-col gap-4">
              <h3 className="text-base font-semibold text-foreground">Auto-Scrape Settings</h3>
              <p className="text-[13px] text-muted-foreground">Automatically fetch updates from added URLs on a schedule.</p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  title="Toggle auto-scrape"
                  onClick={() => setAutoScrape(!autoScrape)}
                  className={`w-11 h-6 rounded-full relative transition-colors ${autoScrape ? "bg-brand" : "bg-muted-foreground/30"}`}
                >
                  <div className={`w-[18px] h-[18px] bg-background rounded-full absolute top-[3px] transition-all ${autoScrape ? "right-[3px]" : "left-[3px]"}`} />
                </button>
                <span className="text-sm text-foreground">Enable periodic auto-scraping</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">Frequency:</span>
                <div className="flex items-center gap-2 px-3.5 h-10 border border-border rounded-md bg-background">
                  <span className="text-[13px] text-foreground">Every 24 hours</span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-[18px] h-[18px] rounded-[3px] bg-brand flex items-center justify-center shrink-0">
                  <span className="text-[10px] text-brand-foreground font-bold">{"\u2713"}</span>
                </div>
                <span className="text-sm text-foreground">Remind me when login session expires</span>
              </div>
            </div>
          )}

          <div className="w-full h-px bg-border" />

          <div className="flex justify-end gap-4">
            <button type="button" onClick={() => setStep("mode")} className="h-11 px-6 border border-border rounded-lg text-muted-foreground font-medium text-sm hover:border-foreground/20">
              Cancel
            </button>
            <button
              type="button"
              onClick={startParsing}
              data-testid="start-parsing"
              disabled={hasUploadErrors}
              className={`h-11 px-7 text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm ${hasUploadErrors ? "bg-brand/50 cursor-not-allowed" : "bg-brand hover:opacity-90"}`}
            >
              Start Parsing &rarr;
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
              Processing -- {projectName || "New Project"}
            </span>
            <div className="flex-1" />
            <StepIndicator currentStep="parsing" />
            <div className={`flex items-center gap-1.5 px-2.5 h-6 rounded ${allJobsFailed ? "bg-destructive/10" : "bg-success-muted"}`}>
              <div className={`w-1.5 h-1.5 rounded-full ${allJobsFailed ? "bg-destructive" : "bg-success"}`} />
              <span className={`text-[11px] font-semibold ${allJobsFailed ? "text-destructive" : "text-success"}`}>
                {allJobsFailed ? "Needs attention" : "Active"}
              </span>
            </div>
          </div>

          <div className="flex flex-1 min-h-0">
            {/* Main content (left) */}
            <div className="flex-1 flex flex-col bg-background">
              {url && (
                <div className="h-9 px-4 bg-muted border-b border-border flex items-center gap-2">
                  <span className="text-xs text-muted-foreground flex-1 truncate">{url}</span>
                  {!canContinueToFeatures && <span className="text-xs text-muted-foreground animate-pulse">loading...</span>}
                </div>
              )}
              <div className="flex-1 p-6 bg-muted/50 flex flex-col gap-4 overflow-y-auto">
                <h2 className="text-xl font-bold text-foreground">Processing your materials...</h2>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Progress now comes directly from backend ingestion jobs. If you enter early, the workspace will keep updating while imports finish.
                </p>
                {files.length > 0 && (
                  <div className="p-3 px-4 bg-warning-muted border border-warning/30 rounded-md text-sm text-warning leading-relaxed">
                    Processing {files.length} file{files.length > 1 ? "s" : ""}: {files.map((f) => f.name).join(", ")}
                  </div>
                )}
                {allJobsFailed && (
                  <div className="p-3 px-4 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive leading-relaxed">
                    All ingestion jobs failed. Review the processing log for the backend error details, then go back and retry.
                  </div>
                )}
              </div>
            </div>

            {/* Parsing Sidebar (right) */}
            <div className="w-[340px] border-l border-border bg-background flex flex-col shrink-0">
              <div className="h-11 px-4 bg-muted border-b border-border flex items-center gap-2 shrink-0">
                {!canContinueToFeatures && <span className="text-xs text-brand animate-pulse">...</span>}
                <span className="font-semibold text-[13px] text-foreground">Parsing Progress</span>
              </div>
              <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto">
                <div className="flex flex-col gap-1.5">
                  <span className="font-semibold text-sm text-foreground">
                    {projectName || "New Project"}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {files.length} file{files.length !== 1 ? "s" : ""}{url ? " + 1 URL source" : ""}
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
                  <span className="text-xs font-medium text-brand">{parseProgress}% complete</span>
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
                  <span className="text-xs font-semibold text-muted-foreground">Processing Log</span>
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
                      Enter now
                    </button>
                  )}
                  {canContinueToFeatures && (
                    <button
                      type="button"
                      onClick={() => setStep("features")}
                      data-testid="continue-to-features"
                      className="w-full h-11 bg-brand text-brand-foreground rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:opacity-90"
                    >
                      Continue to Features &rarr;
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
            <button type="button" onClick={() => setStep("parsing")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
              &larr; Back
            </button>
            <div className="w-px h-4 bg-border" />
            <span className="font-semibold text-sm text-foreground">
              {projectName || "New Project"}
            </span>
            <div className="flex-1" />
            <StepIndicator currentStep="features" />
          </div>

          <div className="flex flex-col gap-2">
            <h1 className="text-[28px] font-bold text-foreground">
              What should Agent do for you?
            </h1>
            <p className="text-[15px] text-muted-foreground">Select the features you want to enable for this project. You can change these later.</p>
          </div>

          {/* Feature Cards -- 2-column grid */}
          <div className="grid grid-cols-2 gap-4">
            {FEATURE_CARDS.map((card) => (
              <button
                type="button"
                key={card.id}
                onClick={() => toggleFeature(card.id)}
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
                    {card.label}
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
                <p className="text-[13px] text-muted-foreground">{card.description}</p>
              </button>
            ))}
          </div>

          {/* NL Input */}
          <div className="flex flex-col gap-2.5">
            <span className="font-semibold text-[15px] text-foreground">
              Anything else you&apos;d like to tell Agent?
            </span>
            <textarea
              className="w-full h-20 p-3 border border-border rounded-lg bg-background resize-none text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
              placeholder='e.g. "Use bullet points for notes", "Focus on algorithms", "Explain in simple terms"...'
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
            />
          </div>

          <div className="w-full h-px bg-border" />

          <div className="flex justify-end gap-4">
            <button type="button" onClick={() => setStep("parsing")} className="h-11 px-6 border border-border rounded-lg text-muted-foreground font-medium text-sm hover:border-foreground/20">
              Back
            </button>
            <button
              type="button"
              onClick={enterWorkspace}
              data-testid="enter-workspace"
              className="h-11 px-7 bg-brand text-brand-foreground rounded-lg flex items-center gap-2 font-semibold text-sm hover:opacity-90"
            >
              Enter Workspace &rarr;
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
                Canvas Login
              </h2>
              {!canvasLogging && (
                <button
                  type="button"
                  onClick={() => setShowCanvasLogin(false)}
                  title="Close"
                  className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground"
                >
                  x
                </button>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">Canvas URL</label>
              <div className="h-10 px-3 flex items-center border border-border rounded-lg bg-muted text-sm text-muted-foreground truncate">
                {url.trim()}
              </div>
            </div>

            {canvasLogging && (
              <div className="flex flex-col items-center gap-4 py-6">
                <div className="w-10 h-10 border-3 border-brand border-t-transparent rounded-full animate-spin" />
                <p className="text-sm font-medium text-foreground">
                  A browser window has opened
                </p>
                <p className="text-[13px] text-muted-foreground text-center leading-relaxed">
                  Please complete your university login (Okta / SSO / MFA) in the browser window.
                  This dialog will close automatically once login is detected.
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
                  onClick={() => setShowCanvasLogin(false)}
                  className="h-10 px-5 border border-border rounded-lg text-sm font-medium text-muted-foreground hover:border-foreground/20"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleAddUrl}
                  className="h-10 px-5 rounded-lg text-sm font-semibold text-brand-foreground bg-brand hover:opacity-90"
                >
                  Retry
                </button>
              </div>
            )}

            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {canvasLogging
                ? "Your session cookies will be saved locally after login. No passwords are stored."
                : "Login timed out or was cancelled. Click Retry to open the browser again."}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
