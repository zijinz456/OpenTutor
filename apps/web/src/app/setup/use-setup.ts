"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getHealthStatus,
  getLlmRuntimeConfig,
  updateLlmRuntimeConfig,
  testLlmRuntimeConnection,
  getDemoCourse,
  type HealthStatus,
  type LlmRuntimeConfig,
  type LlmConnectionTestResult,
  type IngestionJobSummary,
  listIngestionJobs,
  listAuthSessions,
  canvasBrowserLogin,
  streamChat,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { useCourseStore } from "@/store/course";
import type { LearningMode } from "@/lib/block-system/types";
import type { FileItem, ParseLog } from "../new/types";
import { deriveParseSteps, deriveParseProgress } from "../new/types";
import { submitSources } from "../new/parse-actions";
import {
  validateNameValue,
  validateUrlValue,
  applyDefaultPreferences,
  buildCourseMetadata,
  persistWorkspaceLayout,
} from "./setup-helpers";

import type { SpaceLayoutResponse } from "@/lib/api/onboarding";

export type SetupStep = "llm" | "content" | "interview" | "template" | "discovery";

export function useSetup() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const { addCourse } = useCourseStore();

  // ── Step (honor ?step=content query param for returning users) ──
  const initialStep = (searchParams.get("step") as SetupStep) || "llm";
  const [step, setStep] = useState<SetupStep>(
    ["llm", "content", "interview", "template", "discovery"].includes(initialStep) ? initialStep : "llm"
  );

  // ── LLM state ──
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [llmConfig, setLlmConfig] = useState<LlmRuntimeConfig | null>(null);
  const [llmReady, setLlmReady] = useState(false);
  const [llmChecking, setLlmChecking] = useState(true);
  const [llmProvider, setLlmProvider] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmTesting, setLlmTesting] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<LlmConnectionTestResult | null>(null);
  const [llmTestError, setLlmTestError] = useState<string | null>(null);

  // ── Content state ──
  const [projectName, setProjectName] = useState("");
  const [files, setFilesRaw] = useState<FileItem[]>([]);
  // Auto-generate project name from first file
  const setFiles = useCallback((newFiles: FileItem[] | ((prev: FileItem[]) => FileItem[])) => {
    setFilesRaw((prev) => {
      const resolved = typeof newFiles === "function" ? newFiles(prev) : newFiles;
      if (resolved.length > 0 && !projectName.trim()) {
        const name = resolved[0].file.name.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
        setProjectName(name);
      }
      return resolved;
    });
  }, [projectName]);
  const [url, setUrl] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isCanvasDetected, setIsCanvasDetected] = useState(false);
  const [canvasSessionValid, setCanvasSessionValid] = useState(false);
  const [showCanvasLogin, setShowCanvasLogin] = useState(false);
  const [canvasLogging, setCanvasLogging] = useState(false);
  const [canvasLoginError, setCanvasLoginError] = useState<string | null>(null);
  const [autoScrape, setAutoScrape] = useState(true);

  // ── Interview state ──
  const [interviewLayout, setInterviewLayout] = useState<SpaceLayoutResponse | null>(null);

  // ── Template + Mode state ──
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState<LearningMode | null>(null);

  // ── Parsing state ──
  const [createdCourseId, setCreatedCourseId] = useState<string | null>(null);
  const [ingestionJobs, setIngestionJobs] = useState<IngestionJobSummary[]>([]);
  const [isSubmittingContent, setIsSubmittingContent] = useState(false);
  const [noSourcesSubmitted, setNoSourcesSubmitted] = useState(false);
  const [parseLogs, setParseLogs] = useState<ParseLog[]>([]);
  const seenJobStatesRef = useRef<Record<string, string>>({});

  // ── Discovery state ──
  const [aiProbeResponse, setAiProbeResponse] = useState("");
  const [aiProbeStreaming, setAiProbeStreaming] = useState(false);
  const [aiProbeDone, setAiProbeDone] = useState(false);
  const [canEnterEarly, setCanEnterEarly] = useState(false);
  const probeSentRef = useRef(false);

  // ── Derived ──
  const parseSteps = useMemo(
    () => deriveParseSteps(ingestionJobs, isSubmittingContent, noSourcesSubmitted, t),
    [ingestionJobs, isSubmittingContent, noSourcesSubmitted, t],
  );
  const parseProgress = useMemo(
    () => deriveParseProgress(ingestionJobs, isSubmittingContent, noSourcesSubmitted),
    [ingestionJobs, isSubmittingContent, noSourcesSubmitted],
  );
  const hasCompletedJob = ingestionJobs.some((job) => job.status === "completed");
  const allJobsFailed = ingestionJobs.length > 0 && ingestionJobs.every((job) => job.status === "failed");

  // ── LLM check on mount ──
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const [h, cfg] = await Promise.all([getHealthStatus(), getLlmRuntimeConfig()]);
        if (cancelled) return;
        setHealth(h);
        setLlmConfig(cfg);
        setLlmProvider(cfg.provider);
        setLlmModel(cfg.model);

        if (h.llm_status === "ready") {
          setLlmReady(true);
        }
      } catch {
        // Failed to check — show config UI
      } finally {
        if (!cancelled) setLlmChecking(false);
      }
    }
    void check();
    return () => { cancelled = true; };
  }, []);

  // Auto-advance from LLM step when ready (instant — no delay)
  useEffect(() => {
    if (step === "llm" && llmReady && !llmChecking) {
      setStep("content");
    }
  }, [step, llmReady, llmChecking]);

  // ── LLM test + save ──
  const testAndSaveLlm = useCallback(async () => {
    setLlmTesting(true);
    setLlmTestError(null);
    setLlmTestResult(null);
    try {
      const result = await testLlmRuntimeConnection({
        provider: llmProvider,
        model: llmModel || undefined,
        api_key: llmApiKey || undefined,
      });
      setLlmTestResult(result);
      if (result.ok) {
        const providerKeys: Record<string, string> = {};
        if (llmApiKey) providerKeys[llmProvider] = llmApiKey;
        await updateLlmRuntimeConfig({
          provider: llmProvider,
          model: llmModel,
          provider_keys: Object.keys(providerKeys).length > 0 ? providerKeys : undefined,
          base_url: llmBaseUrl || undefined,
        });
        setLlmReady(true);
      } else {
        setLlmTestError(result.response_preview || t("setup.llmTestFailed"));
      }
    } catch (err) {
      setLlmTestError((err as Error).message);
    } finally {
      setLlmTesting(false);
    }
  }, [llmApiKey, llmBaseUrl, llmModel, llmProvider, t]);

  // ── Validation ──
  function validateName(value: string): void {
    setNameError(validateNameValue(value, t));
  }

  function validateUrl(value: string): void {
    const { error, isCanvas } = validateUrlValue(value, t);
    setUrlError(error);
    setIsCanvasDetected(isCanvas);
    if (isCanvas && !canvasSessionValid) {
      void checkCanvasSession(value.trim());
    }
  }

  // ── Check existing Canvas auth session (non-blocking) ──
  const checkCanvasSession = useCallback(async (canvasUrl: string) => {
    try {
      const sessions = await listAuthSessions();
      const domain = new URL(canvasUrl).hostname;
      const match = sessions.find((s) => s.is_valid && domain.includes(s.domain));
      if (match) setCanvasSessionValid(true);
    } catch { /* ignore — will prompt login */ }
  }, []);

  // ── Canvas auth handler (browser login) ──
  const handleAuthCanvas = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    // First try existing sessions
    try {
      const sessions = await listAuthSessions();
      const domain = new URL(trimmed).hostname;
      const match = sessions.find((s) => s.is_valid && domain.includes(s.domain));
      if (match) { setCanvasSessionValid(true); return; }
    } catch { /* proceed to login */ }
    // Open browser login
    setCanvasLoginError(null);
    setShowCanvasLogin(true);
    setCanvasLogging(true);
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

  // ── Ingestion job polling ──
  useEffect(() => {
    if (step !== "discovery" || !createdCourseId || noSourcesSubmitted) return;
    let cancelled = false;
    const pollJobs = async () => {
      const newLogs: ParseLog[] = [];
      try {
        const jobs = await listIngestionJobs(createdCourseId);
        if (cancelled) return;
        setIngestionJobs(jobs);
        for (const job of jobs) {
          const stateKey = `${job.status}:${job.embedding_status}:${job.error_message ?? ""}`;
          if (seenJobStatesRef.current[job.id] === stateKey) continue;
          seenJobStatesRef.current[job.id] = stateKey;
          const label = job.filename || tRef.current("new.untitledSource");
          if (job.error_message) {
            newLogs.push({ text: `${label}: ${job.error_message}`, color: "text-destructive" });
          } else if (job.phase_label) {
            newLogs.push({ text: `${label}: ${job.phase_label}`, color: "text-muted-foreground" });
          }
        }
      } catch {
        // ignore polling errors
      }
      if (newLogs.length > 0 && !cancelled) {
        setParseLogs((prev) => [...prev, ...newLogs]);
      }
    };
    let interval = 2000;
    const maxInterval = 10000;
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(async () => {
        await pollJobs();
        if (!cancelled) {
          interval = Math.min(interval * 1.5, maxInterval);
          schedule();
        }
      }, interval);
    };
    void pollJobs();
    schedule();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [createdCourseId, noSourcesSubmitted, step]);

  // ── Enable "Enter Workspace" after 5s even if ingestion is still running ──
  useEffect(() => {
    if (step !== "discovery" || !createdCourseId) return;
    const timer = window.setTimeout(() => setCanEnterEarly(true), 5000);
    return () => window.clearTimeout(timer);
  }, [step, createdCourseId]);

  // ── AI Probe: auto-send analysis request when first job completes ──
  useEffect(() => {
    if (!hasCompletedJob || !createdCourseId || probeSentRef.current) return;
    probeSentRef.current = true;
    setAiProbeStreaming(true);

    const controller = new AbortController();
    (async () => {
      try {
        const gen = streamChat({
          courseId: createdCourseId,
          message: "Analyze what I've uploaded and identify 3 key concepts I should test my understanding of. Be concise.",
          activeTab: "chat",
          signal: controller.signal,
        });
        for await (const event of gen) {
          if (event.type === "content") {
            setAiProbeResponse((prev) => prev + event.content);
          } else if (event.type === "replace") {
            setAiProbeResponse(event.content);
          } else if (event.type === "done") {
            break;
          }
        }
      } catch {
        // Aborted or failed — non-critical
      } finally {
        setAiProbeStreaming(false);
        setAiProbeDone(true);
      }
    })();

    return () => controller.abort();
  }, [hasCompletedJob, createdCourseId]);

  // ── Start learning (Content → Interview) ──
  const startLearning = useCallback(async () => {
    setStep("interview");
  }, []);

  // ── Interview complete — apply AI-recommended layout and proceed ──
  const acceptInterviewLayout = useCallback((layout: SpaceLayoutResponse) => {
    setInterviewLayout(layout);
    if (layout.mode) {
      setSelectedMode(layout.mode as LearningMode);
    }
    setSelectedTemplate(layout.templateId);
    // Skip manual template selection, go directly to confirm+discovery
    setStep("template");
  }, []);

  // ── Skip interview — go to manual template selection ──
  const skipInterview = useCallback(() => {
    setStep("template");
  }, []);

  // ── Confirm template: create course and continue with discovery before workspace ──
  const confirmTemplate = useCallback(async () => {
    try {
      const { metadata, sourceMode } = buildCourseMetadata(files, url, selectedTemplate, selectedMode);
      const course = await addCourse(projectName.trim() || t("new.untitledProject"), undefined, metadata);

      await applyDefaultPreferences();
      persistWorkspaceLayout(course.id, selectedTemplate, selectedMode, interviewLayout);

      setCreatedCourseId(course.id);
      setIngestionJobs([]);
      setParseLogs([]);
      setNoSourcesSubmitted(false);
      setCanEnterEarly(false);
      setAiProbeResponse("");
      setAiProbeDone(false);
      setAiProbeStreaming(false);
      seenJobStatesRef.current = {};
      probeSentRef.current = false;
      setStep("discovery");
      setIsSubmittingContent(true);

      const addLog = (text: string, color: string) => {
        setParseLogs((prev) => [...prev, { text, color }]);
      };

      void submitSources({
        course,
        files,
        url,
        mode: sourceMode,
        autoScrape,
        canvasSessionValid,
        projectName,
        addLog,
        setCanvasSessionValid,
        setShowCanvasLogin,
        setCanvasLogging,
        setCanvasLoginError,
        setNoSourcesSubmitted,
        t,
      })
        .catch((err) => {
          addLog((err as Error).message, "text-destructive");
        })
        .finally(() => {
          setIsSubmittingContent(false);
        });
    } catch (err) {
      setNameError((err as Error).message);
    }
  }, [addCourse, autoScrape, canvasSessionValid, files, interviewLayout, projectName, selectedMode, selectedTemplate, t, url]);

  // ── Enter workspace ──
  const enterWorkspace = useCallback(async () => {
    if (!createdCourseId) return;
    // Set default preferences silently
    try { await applyDefaultPreferences(); } catch { /* non-critical */ }
    // Apply template/mode and persist layout (interview layout takes priority)
    persistWorkspaceLayout(createdCourseId, selectedTemplate, selectedMode, interviewLayout);
    router.push(`/course/${createdCourseId}`);
  }, [createdCourseId, interviewLayout, router, selectedMode, selectedTemplate]);

  // ── Demo fast path: one click to a working workspace ──
  const [demoLoading, setDemoLoading] = useState(false);
  const tryDemo = useCallback(async () => {
    setDemoLoading(true);
    try {
      const demo = await getDemoCourse();
      await applyDefaultPreferences();
      persistWorkspaceLayout(demo.id, "stem_student", null);
      router.push(`/course/${demo.id}`);
    } catch (err) {
      setNameError((err as Error).message);
      setDemoLoading(false);
    }
  }, [router]);

  // ── Skip content (empty workspace) ──
  const skipContent = useCallback(async () => {
    try {
      const { metadata } = buildCourseMetadata({ length: 0 }, "", null, null, false);
      const course = await addCourse(projectName.trim() || t("new.untitledProject"), undefined, metadata);
      await applyDefaultPreferences();
      localStorage.setItem("opentutor_onboarded", "true");
      router.push(`/course/${course.id}`);
    } catch (err) {
      setNameError((err as Error).message);
    }
  }, [addCourse, projectName, router, t]);

  return {
    t, step, setStep,
    // LLM
    health, llmConfig, llmReady, llmChecking,
    llmProvider, setLlmProvider, llmModel, setLlmModel,
    llmApiKey, setLlmApiKey, llmBaseUrl, setLlmBaseUrl,
    llmTesting, llmTestResult, llmTestError, testAndSaveLlm,
    // Content
    projectName, setProjectName, nameError, validateName,
    files, setFiles,
    url, setUrl, urlError, validateUrl,
    isCanvasDetected, canvasSessionValid, handleAuthCanvas,
    showCanvasLogin, setShowCanvasLogin, canvasLogging, canvasLoginError,
    autoScrape, setAutoScrape,
    // Parsing + Discovery
    parseSteps, parseProgress, parseLogs,
    hasCompletedJob, allJobsFailed, noSourcesSubmitted,
    aiProbeResponse, aiProbeStreaming, aiProbeDone, canEnterEarly,
    createdCourseId,
    // Interview
    interviewLayout, acceptInterviewLayout, skipInterview,
    // Template + Mode
    selectedTemplate, setSelectedTemplate,
    selectedMode, setSelectedMode,
    // Actions
    startLearning, confirmTemplate, enterWorkspace, skipContent,
    tryDemo, demoLoading,
  };
}
