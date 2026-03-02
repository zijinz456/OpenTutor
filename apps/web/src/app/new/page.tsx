"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Upload,
  Globe,
  Layers,
  X,
  FileText,
  Pencil,
  RotateCcw,
  Calendar,
  MessageCircle,
  ChevronDown,
  Check,
  Lock,
  Loader,
  FolderPlus,
} from "lucide-react";
import {
  IngestionJobSummary,
  createScrapeSource,
  uploadFile,
  scrapeUrl,
  type CourseMetadata,
} from "@/lib/api";
import { useCourseStore } from "@/store/course";

type Mode = "upload" | "url" | "both";
type Step = "mode" | "upload" | "parsing" | "features";

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

const FEATURE_CARDS = [
  { id: "notes", label: "Organize Notes", description: "Restructure your materials into clean, organized notes in your preferred format.", icon: FileText, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
  { id: "practice", label: "Practice Mode", description: "Generate practice questions from your materials. Interactive Q&A with instant feedback.", icon: Pencil, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
  { id: "wrong_answer", label: "Wrong Answer Review", description: "Track, diagnose, and revisit incorrect answers from generated quizzes.", icon: RotateCcw, iconBg: "bg-amber-50", iconColor: "text-amber-600", enabled: true },
  { id: "study_plan", label: "Study Plan", description: "Generate a personalized study plan with scheduled reviews.", icon: Calendar, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
  { id: "free_qa", label: "Free Q&A", description: "Ask any question about your materials and get AI-powered answers with source references.", icon: MessageCircle, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
];

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
    notes: true, practice: true, study_plan: true, free_qa: true, wrong_answer: false,
  });
  const [nlInput, setNlInput] = useState("");
  const [createdCourseId, setCreatedCourseId] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
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
    if (value.trim() && !/^https?:\/\//i.test(value.trim())) {
      setUrlError("URL must start with http:// or https://");
    } else {
      setUrlError(null);
    }
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
            addLog(`${new Date().toLocaleTimeString()}  ${label}: ${job.error_message}`, "text-red-500");
          } else if (job.phase_label) {
            addLog(`${new Date().toLocaleTimeString()}  ${label}: ${job.phase_label}`, "text-gray-500");
          }
        }
      } catch (error) {
        if (!cancelled) {
          addLog(
            `${new Date().toLocaleTimeString()}  Failed to refresh ingestion status: ${(error as Error).message}`,
            "text-red-500",
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

      // Create the course
      addLog(`${new Date().toLocaleTimeString()}  Creating project "${projectName || "Untitled"}"...`, "text-gray-400");
      const description = nlInput.trim() || undefined;
      const course = await addCourse(projectName.trim() || "Untitled Project", description, metadata);
      nextCourseId = course.id;
      setCreatedCourseId(course.id);

      addLog(`${new Date().toLocaleTimeString()}  Project created`, "text-green-500");
      const hasSources = files.length > 0 || (url.trim() && (mode === "url" || mode === "both"));
      if (!hasSources) {
        setNoSourcesSubmitted(true);
        addLog(
          `${new Date().toLocaleTimeString()}  No files or URLs submitted. You can continue and add content later.`,
          "text-gray-500",
        );
        return;
      }

      if (files.length > 0) {
        for (const f of files) {
          addLog(`${new Date().toLocaleTimeString()}  Uploading ${f.name}...`, "text-gray-400");
          try {
            const result = await uploadFile(course.id, f.file);
            addLog(
              `${new Date().toLocaleTimeString()}  ${f.name}: ${result.nodes_created} nodes queued`,
              "text-green-500",
            );
          } catch (err) {
            addLog(`${new Date().toLocaleTimeString()}  Failed: ${f.name} — ${(err as Error).message}`, "text-red-500");
          }
        }
      }

      // Step 3: Scrape URL
      if (url.trim() && (mode === "url" || mode === "both")) {
        addLog(`${new Date().toLocaleTimeString()}  Fetching ${url}...`, "text-gray-400");
        try {
          const result = await scrapeUrl(course.id, url.trim());
          addLog(
            `${new Date().toLocaleTimeString()}  URL content accepted: ${result.nodes_created} nodes queued`,
            "text-green-500",
          );
          if (autoScrape) {
            await createScrapeSource({
              course_id: course.id,
              url: url.trim(),
              label: projectName.trim() || "Project source",
              interval_hours: 24,
            });
            addLog(
              `${new Date().toLocaleTimeString()}  Auto-scrape enabled for this URL (every 24 hours)`,
              "text-green-500",
            );
          }
        } catch (err) {
          addLog(`${new Date().toLocaleTimeString()}  Scrape failed: ${(err as Error).message}`, "text-red-500");
        }
      }
    } catch (err) {
      addLog(`${new Date().toLocaleTimeString()}  Error: ${(err as Error).message}`, "text-red-500");
    } finally {
      setIsSubmittingContent(false);
      if (nextCourseId) {
        void fetchContentTree(nextCourseId).catch(() => undefined);
      }
    }
  }, [addCourse, autoScrape, features, fetchContentTree, files, mode, nlInput, projectName, url]);

  const enterWorkspace = () => {
    if (!createdCourseId) return;

    // Store the NL instruction so the workspace can send it as the first chat message
    if (nlInput.trim()) {
      localStorage.setItem(`course_init_prompt_${createdCourseId}`, nlInput.trim());
    }

    router.push(`/course/${createdCourseId}`);
  };

  return (
    <div className="min-h-screen bg-white">
      {/* MODE SELECTION (Page 2 in ref) */}
      {step === "mode" && (
        <div className="h-screen flex items-center justify-center">
          <div className="w-[640px] flex flex-col gap-10 items-center animate-in fade-in duration-300">
            <div className="flex flex-col gap-3 items-center text-center">
              <div className="w-14 h-14 bg-indigo-50 rounded-[14px] flex items-center justify-center">
                <FolderPlus className="w-7 h-7 text-indigo-600" />
              </div>
              <h1 className="text-[32px] font-bold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                How would you like to add content?
              </h1>
              <p className="text-[15px] text-gray-500 max-w-[480px] leading-relaxed">
                Choose how you want to bring learning materials into your new project.
              </p>
            </div>

            <div className="flex gap-4 w-full">
              {[
                { key: "upload" as Mode, icon: Upload, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", label: "Upload Documents", desc: "Upload PDF, PPT, DOCX files from your computer" },
                { key: "url" as Mode, icon: Globe, iconBg: "bg-green-50", iconColor: "text-green-600", label: "Scrape from URL", desc: "Auto-fetch content from course websites and pages" },
                { key: "both" as Mode, icon: Layers, iconBg: "bg-violet-50", iconColor: "text-violet-600", label: "Both", desc: "Upload files and scrape URLs together" },
              ].map((m) => (
                <button
                  key={m.key}
                  onClick={() => setMode(m.key)}
                  data-testid={`mode-option-${m.key}`}
                  className={`flex-1 flex flex-col items-center justify-center gap-3.5 p-7 rounded-[10px] transition-all ${
                    mode === m.key
                      ? "border-2 border-indigo-600 bg-indigo-50"
                      : "border border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className={`w-12 h-12 ${m.iconBg} rounded-xl flex items-center justify-center`}>
                    <m.icon className={`w-6 h-6 ${m.iconColor}`} />
                  </div>
                  <span className="font-semibold text-base text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    {m.label}
                  </span>
                  <span className="text-[13px] text-gray-400 text-center leading-snug">{m.desc}</span>
                </button>
              ))}
            </div>

            <div className="flex justify-between w-full mt-2">
              <button
                onClick={() => router.push("/")}
                className="h-11 px-6 border border-gray-200 rounded-lg flex items-center gap-1.5 text-gray-500 font-medium text-sm hover:border-gray-300"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back to Projects
              </button>
              <button
                onClick={() => setStep("upload")}
                data-testid="mode-continue"
                className="h-11 px-7 bg-indigo-600 text-white rounded-lg flex items-center gap-2 font-semibold text-sm hover:bg-indigo-700"
              >
                Continue <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* UPLOAD FORM (Page 3 in ref) */}
      {step === "upload" && (
        <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
          {/* Top nav */}
          <div className="flex items-center gap-3">
            <button onClick={() => setStep("mode")} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700">
              <ArrowLeft className="w-[18px] h-[18px]" /> Back
            </button>
            <div className="w-px h-4 bg-gray-200" />
            <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Create New Project</span>
            <div className="flex-1" />
            <span className="px-2 py-1 bg-indigo-50 text-indigo-600 text-[11px] font-medium rounded">
              {mode === "upload" ? "Upload Documents" : mode === "url" ? "Scrape from URL" : "Both: Upload + URL"}
            </span>
          </div>

          {/* Project Name */}
          <div className="flex flex-col gap-2">
            <label className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Project Name</label>
            <input
              data-testid="project-name-input"
              className={`w-full h-11 px-4 border rounded-lg bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600 ${nameError ? "border-red-400" : "border-gray-200"}`}
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
              <h3 className="text-base font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Upload Learning Materials</h3>
              <div
                className={`w-full h-40 border-2 border-dashed rounded-lg flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors ${
                  dragging
                    ? "border-indigo-600 bg-indigo-50"
                    : "border-gray-200 bg-gray-50 hover:border-indigo-600 hover:bg-indigo-50"
                }`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={handleDragOver}
                onDragEnter={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <Upload className={`w-8 h-8 ${dragging ? "text-indigo-600" : "text-gray-400"}`} />
                <span className={`text-sm ${dragging ? "text-indigo-600 font-medium" : "text-gray-500"}`}>
                  {dragging ? "Drop files here" : "Drag files here, or click to browse"}
                </span>
                <span className="text-xs text-gray-400">Supports PDF, PPT, DOCX</span>
              </div>
              <input
                ref={fileInputRef}
                data-testid="project-file-input"
                type="file"
                accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
                multiple
                className="hidden"
                onChange={handleFileAdd}
              />
              {files.length > 0 && (
                <div className="flex flex-col gap-2">
                  {files.map((f, idx) => (
                    <div key={idx} className="flex items-center gap-3 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg">
                      <FileText className="w-4 h-4 text-indigo-600" />
                      <span className="text-[13px] flex-1 text-gray-900">{f.name}</span>
                      <span className="text-xs text-gray-400">{f.size}</span>
                      <button onClick={() => removeFile(idx)}>
                        <X className="w-3.5 h-3.5 text-gray-400 hover:text-gray-700" />
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
              <h3 className="text-base font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Add URL</h3>
              <div className="flex gap-2">
                <input
                  className={`flex-1 h-11 px-4 border rounded-lg bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600 ${urlError ? "border-red-400" : "border-gray-200"}`}
                  placeholder="https://professor-site.edu/cs101/"
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    validateUrl(e.target.value);
                  }}
                  onBlur={() => validateUrl(url)}
                />
                <button className="h-11 px-5 bg-indigo-600 text-white rounded-lg font-semibold text-sm hover:bg-indigo-700">Add</button>
              </div>
              {urlError && <p className="text-xs text-destructive mt-1">{urlError}</p>}
            </div>
          )}

          {/* Auto-Scrape Settings */}
          {(mode === "url" || mode === "both") && (
            <div className="flex flex-col gap-4">
              <h3 className="text-base font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Auto-Scrape Settings</h3>
              <p className="text-[13px] text-gray-500">Automatically fetch updates from added URLs on a schedule.</p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setAutoScrape(!autoScrape)}
                  className={`w-11 h-6 rounded-full relative transition-colors ${autoScrape ? "bg-indigo-600" : "bg-gray-300"}`}
                >
                  <div className={`w-[18px] h-[18px] bg-white rounded-full absolute top-[3px] transition-all ${autoScrape ? "right-[3px]" : "left-[3px]"}`} />
                </button>
                <span className="text-sm text-gray-900">Enable periodic auto-scraping</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-gray-500">Frequency:</span>
                <div className="flex items-center gap-2 px-3.5 h-10 border border-gray-200 rounded-md bg-white">
                  <span className="text-[13px] text-gray-900">Every 24 hours</span>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-[18px] h-[18px] rounded-[3px] bg-indigo-600 flex items-center justify-center shrink-0">
                  <Check className="w-3 h-3 text-white" />
                </div>
                <span className="text-sm text-gray-900">Remind me when login session expires</span>
              </div>
            </div>
          )}

          <div className="w-full h-px bg-gray-200" />

          <div className="flex justify-end gap-4">
            <button onClick={() => setStep("mode")} className="h-11 px-6 border border-gray-200 rounded-lg text-gray-500 font-medium text-sm hover:border-gray-300">
              Cancel
            </button>
            <button
              onClick={startParsing}
              data-testid="start-parsing"
              disabled={hasUploadErrors}
              className={`h-11 px-7 text-white rounded-lg flex items-center gap-2 font-semibold text-sm ${hasUploadErrors ? "bg-indigo-400 cursor-not-allowed" : "bg-indigo-600 hover:bg-indigo-700"}`}
            >
              Start Parsing <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* PARSING PROGRESS (Page 4 in ref) */}
      {step === "parsing" && (
        <div className="h-screen flex animate-in fade-in duration-300">
          {/* Browser Preview (left) */}
          <div className="flex-1 flex flex-col bg-white">
            <div className="h-12 px-5 bg-gray-50 border-b flex items-center gap-3 shrink-0">
              <Globe className="w-[18px] h-[18px] text-indigo-600" />
              <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                Processing — {projectName || "New Project"}
              </span>
              <div className="flex-1" />
              <div className={`flex items-center gap-1.5 px-2.5 h-6 rounded ${allJobsFailed ? "bg-red-50" : "bg-green-50"}`}>
                <div className={`w-1.5 h-1.5 rounded-full ${allJobsFailed ? "bg-red-500" : "bg-green-500"}`} />
                <span className={`text-[11px] font-semibold ${allJobsFailed ? "text-red-600" : "text-green-600"}`}>
                  {allJobsFailed ? "Needs attention" : "Active"}
                </span>
              </div>
            </div>
            {url && (
              <div className="h-9 px-3 bg-white border-b flex items-center gap-2">
                <Lock className="w-3 h-3 text-green-500" />
                <span className="text-xs text-gray-500 flex-1">{url}</span>
                <Loader className="w-3.5 h-3.5 text-gray-400 animate-spin" />
              </div>
            )}
            <div className="flex-1 p-6 bg-gray-50 flex flex-col gap-4 overflow-y-auto">
              <h2 className="text-xl font-bold text-gray-900">Processing your materials...</h2>
              <p className="text-sm text-gray-600 leading-relaxed">
                Progress now comes directly from backend ingestion jobs. If you enter early, the workspace will keep updating while imports finish.
              </p>
              {files.length > 0 && (
                <div className="p-3 px-4 bg-yellow-50 border border-yellow-200 rounded-md text-sm text-yellow-800 leading-relaxed">
                  Processing {files.length} file{files.length > 1 ? "s" : ""}: {files.map((f) => f.name).join(", ")}
                </div>
              )}
              {allJobsFailed && (
                <div className="p-3 px-4 bg-red-50 border border-red-200 rounded-md text-sm text-red-700 leading-relaxed">
                  All ingestion jobs failed. Review the processing log for the backend error details, then go back and retry.
                </div>
              )}
            </div>
          </div>

          {/* Parsing Sidebar (right) */}
          <div className="w-[340px] border-l bg-white flex flex-col shrink-0">
            <div className="h-11 px-4 bg-gray-50 border-b flex items-center gap-2 shrink-0">
              <Loader className={`w-4 h-4 text-indigo-600 ${!canContinueToFeatures ? "animate-spin" : ""}`} />
              <span className="font-semibold text-[13px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Parsing Progress</span>
            </div>
            <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto">
              <div className="flex flex-col gap-1.5">
                <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                  {projectName || "New Project"}
                </span>
                <span className="text-xs text-gray-400">
                  {files.length} file{files.length !== 1 ? "s" : ""}{url ? " + 1 URL source" : ""}
                </span>
              </div>

              {/* Progress bar */}
              <div className="flex flex-col gap-1.5">
                <div className="w-full h-1.5 bg-gray-100 rounded-full">
                  <div
                    className="h-1.5 bg-indigo-600 rounded-full transition-all duration-500"
                    style={{ width: `${parseProgress}%` }}
                  />
                </div>
                <span className="text-xs font-medium text-indigo-600">{parseProgress}% complete</span>
              </div>

              {/* Steps */}
              <div className="flex flex-col gap-3">
                {parseSteps.map((ps, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <div
                      className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${
                        ps.status === "done"
                          ? "bg-green-500"
                          : ps.status === "active"
                          ? "bg-indigo-600"
                          : "border border-gray-200"
                      }`}
                    >
                      {ps.status === "done" && <Check className="w-[11px] h-[11px] text-white" />}
                      {ps.status === "active" && <Loader className="w-[11px] h-[11px] text-white animate-spin" />}
                    </div>
                    <span
                      className={`text-xs ${
                        ps.status === "done"
                          ? "text-gray-900 font-medium"
                          : ps.status === "active"
                          ? "text-indigo-600 font-semibold"
                          : "text-gray-400"
                      }`}
                    >
                      {ps.label}
                    </span>
                  </div>
                ))}
              </div>

              <div className="w-full h-px bg-gray-200" />

              {/* Scrape Log */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-semibold text-gray-500">Processing Log</span>
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
                    onClick={enterWorkspace}
                    data-testid="enter-now"
                    className="w-full h-11 border border-gray-200 text-gray-700 rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:border-gray-300"
                  >
                    Enter now
                  </button>
                )}
                {canContinueToFeatures && (
                  <button
                    onClick={() => setStep("features")}
                    data-testid="continue-to-features"
                    className="w-full h-11 bg-indigo-600 text-white rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:bg-indigo-700"
                  >
                    Continue to Features <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* FEATURE SELECTION (Page 5 in ref) */}
      {step === "features" && (
        <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
          {/* Top nav */}
          <div className="flex items-center gap-3">
            <button onClick={() => setStep("parsing")} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700">
              <ArrowLeft className="w-[18px] h-[18px]" /> Back
            </button>
            <div className="w-px h-4 bg-gray-200" />
            <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              {projectName || "New Project"}
            </span>
          </div>

          <div className="flex flex-col gap-2">
            <h1 className="text-[28px] font-bold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              What should Agent do for you?
            </h1>
            <p className="text-[15px] text-gray-500">Select the features you want to enable for this project. You can change these later.</p>
          </div>

          {/* Feature Cards — 2-column grid */}
          <div className="grid grid-cols-2 gap-4">
            {FEATURE_CARDS.map((card) => (
              <button
                key={card.id}
                onClick={() => toggleFeature(card.id)}
                className={`p-5 rounded-xl flex flex-col gap-3 text-left transition-all ${
                  features[card.id]
                    ? "border-2 border-indigo-600"
                    : "border border-gray-200"
                } ${card.phase ? "opacity-60 cursor-default" : "hover:shadow-md"}`}
              >
                <div className="flex items-center gap-2.5 w-full">
                  <div className={`w-9 h-9 ${card.iconBg} rounded-lg flex items-center justify-center shrink-0`}>
                    <card.icon className={`w-[18px] h-[18px] ${card.iconColor}`} />
                  </div>
                  <span className="font-semibold text-base text-gray-900 flex-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    {card.label}
                  </span>
                  {card.phase && (
                    <span className="h-[22px] px-2 bg-amber-50 rounded text-[11px] font-semibold text-amber-600 flex items-center">
                      {card.phase}
                    </span>
                  )}
                  <div
                    className={`w-[22px] h-[22px] rounded flex items-center justify-center shrink-0 ml-auto ${
                      features[card.id] ? "bg-indigo-600" : "border-2 border-gray-200"
                    }`}
                  >
                    {features[card.id] && <Check className="w-3.5 h-3.5 text-white" />}
                  </div>
                </div>
                <p className="text-[13px] text-gray-500">{card.description}</p>
              </button>
            ))}
          </div>

          {/* NL Input */}
          <div className="flex flex-col gap-2.5">
            <span className="font-semibold text-[15px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              Anything else you&apos;d like to tell Agent?
            </span>
            <textarea
              className="w-full h-20 p-3 border border-gray-200 rounded-lg bg-white resize-none text-[13px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
              placeholder='e.g. "Use bullet points for notes", "Focus on algorithms", "Explain in simple terms"...'
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
            />
          </div>

          <div className="w-full h-px bg-gray-200" />

          <div className="flex justify-end gap-4">
            <button onClick={() => setStep("parsing")} className="h-11 px-6 border border-gray-200 rounded-lg text-gray-500 font-medium text-sm hover:border-gray-300">
              Back
            </button>
            <button
              onClick={enterWorkspace}
              data-testid="enter-workspace"
              className="h-11 px-7 bg-indigo-600 text-white rounded-lg flex items-center gap-2 font-semibold text-sm hover:bg-indigo-700"
            >
              Enter Workspace <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
