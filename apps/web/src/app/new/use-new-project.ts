"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  type IngestionJobSummary,
  listIngestionJobs,
  updateCourse,
  listAuthSessions,
  canvasBrowserLogin,
  fetchCanvasCourseInfo,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { persistCourseSpaceLayoutLocally } from "@/lib/block-system/layout-sync";
import { useCourseStore } from "@/store/course";
import { useWorkspaceStore } from "@/store/workspace";
import { buildLayoutFromMode } from "@/lib/block-system/templates";
import type { LearningMode } from "@/lib/block-system/types";

import type { Mode, Step, FileItem, ParseLog } from "./types";
import { isCanvasUrl, FEATURE_CARDS, deriveParseSteps, deriveParseProgress } from "./types";
import { submitSources, buildMetadata } from "./parse-actions";

export function useNewProject() {
  const router = useRouter();
  const t = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const { addCourse, fetchContentTree } = useCourseStore();

  /* ---------- State ---------- */
  const [step, setStep] = useState<Step>("mode");
  const [mode, setMode] = useState<Mode>("both");
  const [learningMode, setLearningMode] = useState<LearningMode>("course_following");
  const [projectName, setProjectName] = useState("");
  const projectNameRef = useRef(projectName);
  projectNameRef.current = projectName;
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
  const [ingestionJobs, setIngestionJobs] = useState<IngestionJobSummary[]>([]);
  const [isSubmittingContent, setIsSubmittingContent] = useState(false);
  const [noSourcesSubmitted, setNoSourcesSubmitted] = useState(false);
  const [parseLogs, setParseLogs] = useState<ParseLog[]>([]);
  const seenJobStatesRef = useRef<Record<string, string>>({});

  /* ---------- Derived values ---------- */
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
  const canContinueToFeatures = noSourcesSubmitted || hasCompletedJob;

  /* ---------- Validation ---------- */
  function validateName(value: string): void {
    if (value.length > 100) {
      setNameError(t("new.projectNameTooLong"));
    } else {
      setNameError(null);
    }
  }

  function validateUrl(value: string): void {
    const trimmed = value.trim();
    if (trimmed && !/^https?:\/\//i.test(trimmed)) {
      setUrlError(t("new.urlInvalid"));
    } else {
      setUrlError(null);
    }
    setIsCanvasDetected(trimmed ? isCanvasUrl(trimmed) : false);
  }

  /* ---------- Feature toggle ---------- */
  function toggleFeature(id: string): void {
    const card = FEATURE_CARDS.find((c) => c.id === id);
    if (card?.phase) return;
    setFeatures((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  /* ---------- Ingestion job polling ---------- */
  useEffect(() => {
    if (step !== "parsing" || !createdCourseId || noSourcesSubmitted) return;

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
            newLogs.push({ text: `${new Date().toLocaleTimeString()}  ${label}: ${job.error_message}`, color: "text-destructive" });
          } else if (job.phase_label) {
            newLogs.push({ text: `${new Date().toLocaleTimeString()}  ${label}: ${job.phase_label}`, color: "text-muted-foreground" });
          }
        }
      } catch (error) {
        if (!cancelled) {
          newLogs.push({ text: `${new Date().toLocaleTimeString()}  ${tRef.current("new.logRefreshFailed")}: ${(error as Error).message}`, color: "text-destructive" });
        }
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

  /* ---------- Auto-fill project name from Canvas ---------- */
  const autoFillCanvasName = useCallback(async (canvasUrl: string) => {
    try {
      const info = await fetchCanvasCourseInfo(canvasUrl);
      if (info.name && !projectNameRef.current.trim()) {
        setProjectName(info.name);
      }
    } catch { /* non-critical */ }
  }, []);

  /* ---------- Canvas URL add handler ---------- */
  const handleAddUrl = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed || !isCanvasUrl(trimmed)) return;

    try {
      const sessions = await listAuthSessions();
      const domain = new URL(trimmed).hostname;
      const match = sessions.find((s) => s.is_valid && domain.includes(s.domain));
      if (match) {
        setCanvasSessionValid(true);
        void autoFillCanvasName(trimmed);
        return;
      }
    } catch { /* prompt login anyway */ }

    setCanvasLoginError(null);
    setShowCanvasLogin(true);
    setCanvasLogging(true);
    try {
      await canvasBrowserLogin(trimmed);
      setCanvasSessionValid(true);
      setShowCanvasLogin(false);
      void autoFillCanvasName(trimmed);
    } catch (err) {
      setCanvasLoginError((err as Error).message || t("new.loginFailed"));
    } finally {
      setCanvasLogging(false);
    }
  }, [t, url, autoFillCanvasName]);

  /* ---------- Start parsing ---------- */
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
      const metadata = {
        ...buildMetadata(features, autoScrape, url, mode),
        learning_mode: learningMode,
      };
      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logCreatingProject")} "${projectName || t("new.untitled")}"...`, "text-muted-foreground");

      const description = nlInput.trim() || undefined;
      const course = await addCourse(projectName.trim() || t("new.untitledProject"), description, metadata);
      nextCourseId = course.id;
      setCreatedCourseId(course.id);
      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logProjectCreated")}`, "text-success");

      await submitSources({
        course, files, url, mode, autoScrape, canvasSessionValid, projectName,
        addLog, setCanvasSessionValid, setShowCanvasLogin, setCanvasLogging,
        setCanvasLoginError, setNoSourcesSubmitted, t,
      });
    } catch (err) {
      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logError")}: ${(err as Error).message}`, "text-destructive");
    } finally {
      setIsSubmittingContent(false);
      if (nextCourseId) void fetchContentTree(nextCourseId).catch(() => undefined);
    }
  }, [
    addCourse,
    autoScrape,
    canvasSessionValid,
    features,
    fetchContentTree,
    files,
    learningMode,
    mode,
    nlInput,
    projectName,
    t,
    url,
  ]);

  /* ---------- Enter workspace ---------- */
  const enterWorkspace = useCallback(async () => {
    if (!createdCourseId) return;
    const layout = buildLayoutFromMode(learningMode);
    const metadata = {
      ...buildMetadata(features, autoScrape, url, mode),
      learning_mode: learningMode,
      spaceLayout: layout,
    };

    // Prime workspace state so the first paint on /course is mode-correct.
    useWorkspaceStore.getState().loadBlocks(layout);
    persistCourseSpaceLayoutLocally(createdCourseId, layout);

    try { await updateCourse(createdCourseId, { metadata }); } catch { /* still works */ }
    if (nlInput.trim()) try { localStorage.setItem(`course_init_prompt_${createdCourseId}`, nlInput.trim()); } catch { /* quota */ }
    router.push(`/course/${createdCourseId}`);
  }, [autoScrape, createdCourseId, features, learningMode, mode, nlInput, router, url]);

  return {
    router, t, step, setStep,
    mode, setMode,
    learningMode, setLearningMode,
    projectName, setProjectName, nameError, validateName,
    files, setFiles,
    url, setUrl, urlError, validateUrl, isCanvasDetected, canvasSessionValid, handleAddUrl,
    autoScrape, setAutoScrape,
    features, toggleFeature, nlInput, setNlInput,
    showCanvasLogin, setShowCanvasLogin, canvasLogging, canvasLoginError,
    parseSteps, parseProgress, parseLogs, canContinueToFeatures, allJobsFailed, createdCourseId,
    startParsing, enterWorkspace,
  };
}
