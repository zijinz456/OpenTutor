"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getHealthStatus,
  getLlmRuntimeConfig,
  updateLlmRuntimeConfig,
  testLlmRuntimeConnection,
  type HealthStatus,
  type LlmRuntimeConfig,
  type LlmConnectionTestResult,
  type IngestionJobSummary,
  listIngestionJobs,
  listAuthSessions,
  canvasBrowserLogin,
  setPreference,
  streamChat,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { updateUnlockContext } from "@/lib/block-system/feature-unlock";
import { TEMPLATES } from "@/lib/block-system/templates";

import type { LearningMode } from "@/lib/block-system/types";
import type { FileItem, ParseLog } from "../new/types";
import { isCanvasUrl, deriveParseSteps, deriveParseProgress } from "../new/types";
import { submitSources, buildMetadata } from "../new/parse-actions";

export type SetupStep = "llm" | "content" | "template" | "discovery";

export function useSetup() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useT();
  const { addCourse } = useCourseStore();

  // ── Step (honor ?step=content query param for returning users) ──
  const initialStep = (searchParams.get("step") as SetupStep) || "llm";
  const [step, setStep] = useState<SetupStep>(
    ["llm", "content", "template", "discovery"].includes(initialStep) ? initialStep : "llm"
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
  const parseSteps = deriveParseSteps(ingestionJobs, isSubmittingContent, noSourcesSubmitted, t);
  const parseProgress = deriveParseProgress(ingestionJobs, isSubmittingContent, noSourcesSubmitted);
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
    if (!value.trim()) setNameError(t("new.projectNameRequired"));
    else if (value.length > 100) setNameError(t("new.projectNameTooLong"));
    else setNameError(null);
  }

  function validateUrl(value: string): void {
    const trimmed = value.trim();
    if (trimmed && !/^https?:\/\//i.test(trimmed)) setUrlError(t("new.urlInvalid"));
    else setUrlError(null);
    const detected = trimmed ? isCanvasUrl(trimmed) : false;
    setIsCanvasDetected(detected);
    // Auto-check existing Canvas sessions when Canvas URL is detected
    if (detected && !canvasSessionValid) {
      void checkCanvasSession(trimmed);
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
          if (seenJobStatesRef.current[job.id] === stateKey) continue;
          seenJobStatesRef.current[job.id] = stateKey;
          const label = job.filename || t("new.untitledSource");
          if (job.error_message) {
            addLog(`${label}: ${job.error_message}`, "text-destructive");
          } else if (job.phase_label) {
            addLog(`${label}: ${job.phase_label}`, "text-muted-foreground");
          }
        }
      } catch {
        // ignore polling errors
      }
    };
    void pollJobs();
    const timer = window.setInterval(() => void pollJobs(), 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [createdCourseId, noSourcesSubmitted, step, t]);

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

  // ── Start parsing (Content → Template → Discovery) ──
  const startLearning = useCallback(async () => {
    setStep("template");
  }, []);

  // ── Confirm template and begin ingestion (Template → Discovery) ──
  const confirmTemplate = useCallback(async () => {
    setStep("discovery");
    setIngestionJobs([]);
    setParseLogs([]);
    setIsSubmittingContent(true);
    setNoSourcesSubmitted(false);
    seenJobStatesRef.current = {};
    probeSentRef.current = false;
    setAiProbeResponse("");
    setAiProbeDone(false);

    const addLog = (text: string, color: string) => {
      setParseLogs((prev) => [...prev, { text, color }]);
    };

    try {
      const features = { notes: true, practice: true, study_plan: true, free_qa: true, wrong_answer: true };
      const sourceMode = files.length > 0 && url.trim() ? "both" : files.length > 0 ? "upload" : "url";
      const modeFromTemplate = selectedTemplate ? TEMPLATES[selectedTemplate]?.defaultMode : undefined;
      const modeForCourse = selectedMode ?? modeFromTemplate;
      const metadata = {
        ...buildMetadata(features, true, url, sourceMode),
        ...(modeForCourse ? { learning_mode: modeForCourse } : {}),
      };
      const course = await addCourse(projectName.trim() || t("new.untitledProject"), undefined, metadata);
      setCreatedCourseId(course.id);
      addLog(t("new.logProjectCreated"), "text-success");

      await submitSources({
        course, files, url, mode: sourceMode, autoScrape: true, canvasSessionValid, projectName,
        addLog, setCanvasSessionValid, setShowCanvasLogin, setCanvasLogging,
        setCanvasLoginError, setNoSourcesSubmitted, t,
      });
    } catch (err) {
      addLog(`${t("new.logError")}: ${(err as Error).message}`, "text-destructive");
    } finally {
      setIsSubmittingContent(false);
    }
  }, [addCourse, canvasSessionValid, files, projectName, selectedMode, selectedTemplate, t, url]);

  // ── Enter workspace ──
  const enterWorkspace = useCallback(async () => {
    if (!createdCourseId) return;
    // Set default preferences silently
    try {
      await Promise.all([
        setPreference("language", "auto", "global"),
        setPreference("learning_mode", "balanced", "global"),
        setPreference("detail_level", "balanced", "global"),
        setPreference("layout_preset", "balanced", "global"),
      ]);
    } catch { /* non-critical */ }
    // Apply selected template and persist to localStorage
    if (selectedTemplate) {
      useWorkspaceStore.getState().applyBlockTemplate(selectedTemplate);
    }
    // Persist selected mode without replacing the chosen template layout.
    if (selectedMode) {
      useWorkspaceStore.getState().setSpaceMode(selectedMode);
    }
    // Persist final layout
    const layout = useWorkspaceStore.getState().spaceLayout;
    if (selectedTemplate || selectedMode) {
      localStorage.setItem(`opentutor_blocks_${createdCourseId}`, JSON.stringify(layout));
      if (layout.mode) {
        updateUnlockContext(createdCourseId, { mode: layout.mode });
      }
    }
    localStorage.setItem("opentutor_onboarded", "true");
    router.push(`/course/${createdCourseId}`);
  }, [createdCourseId, router, selectedMode, selectedTemplate]);

  // ── Skip content (empty workspace) ──
  const skipContent = useCallback(async () => {
    try {
      const features = { notes: true, practice: true, study_plan: true, free_qa: true, wrong_answer: true };
      const metadata = buildMetadata(features, false, "", "upload");
      const course = await addCourse(projectName.trim() || t("new.untitledProject"), undefined, metadata);
      await Promise.all([
        setPreference("language", "auto", "global"),
        setPreference("learning_mode", "balanced", "global"),
        setPreference("detail_level", "balanced", "global"),
        setPreference("layout_preset", "balanced", "global"),
      ]);
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
    // Parsing + Discovery
    parseSteps, parseProgress, parseLogs,
    hasCompletedJob, allJobsFailed, noSourcesSubmitted,
    aiProbeResponse, aiProbeStreaming, aiProbeDone, canEnterEarly,
    createdCourseId,
    // Template + Mode
    selectedTemplate, setSelectedTemplate,
    selectedMode, setSelectedMode,
    // Actions
    startLearning, confirmTemplate, enterWorkspace, skipContent,
  };
}
