import {
  createScrapeSource,
  uploadFile,
  scrapeUrl,
  canvasBrowserLogin,
  type CourseMetadata,
} from "@/lib/api";

import type { Mode, FileItem } from "./types";
import { isCanvasUrl } from "./types";

type LogFn = (text: string, color: string) => void;

interface SubmitSourcesArgs {
  course: { id: string };
  files: FileItem[];
  url: string;
  mode: Mode;
  autoScrape: boolean;
  canvasSessionValid: boolean;
  projectName: string;
  addLog: LogFn;
  setCanvasSessionValid: (v: boolean) => void;
  setShowCanvasLogin: (v: boolean) => void;
  setCanvasLogging: (v: boolean) => void;
  setCanvasLoginError: (v: string | null) => void;
  setNoSourcesSubmitted: (v: boolean) => void;
  t: (key: string) => string;
}

/**
 * Uploads files and scrapes URLs for a newly created course.
 * Returns true if at least one source was submitted, false otherwise.
 */
export async function submitSources(args: SubmitSourcesArgs): Promise<boolean> {
  const {
    course, files, url, mode, autoScrape, canvasSessionValid,
    projectName, addLog, setCanvasSessionValid, setShowCanvasLogin,
    setCanvasLogging, setCanvasLoginError, setNoSourcesSubmitted, t,
  } = args;

  const hasSources = files.length > 0 || (url.trim() && (mode === "url" || mode === "both"));
  if (!hasSources) {
    setNoSourcesSubmitted(true);
    addLog(`${new Date().toLocaleTimeString()}  ${t("new.logNoSources")}`, "text-muted-foreground");
    return false;
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
      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logCanvasOpening")}`, "text-warning");
      setShowCanvasLogin(true);
      setCanvasLogging(true);
      try {
        await canvasBrowserLogin(url.trim());
        setCanvasSessionValid(true);
        setShowCanvasLogin(false);
        addLog(`${new Date().toLocaleTimeString()}  ${t("new.logCanvasLoginSucceeded")}`, "text-success");
      } catch (loginErr) {
        setCanvasLoginError((loginErr as Error).message || t("new.loginFailed"));
        setCanvasLogging(false);
        addLog(`${new Date().toLocaleTimeString()}  ${t("new.logCanvasLoginFailed")}: ${(loginErr as Error).message}`, "text-destructive");
        addLog(`${new Date().toLocaleTimeString()}  ${t("new.logBrowserTip")}`, "text-warning");
        return true;
      } finally {
        setCanvasLogging(false);
      }
    }

    // Create scrape source FIRST so periodic retry works even if initial scrape fails
    if (autoScrape) {
      try {
        await createScrapeSource({
          course_id: course.id,
          url: url.trim(),
          label: projectName.trim() || t("new.untitledSource"),
          source_type: urlIsCanvas ? "canvas" : "generic",
          requires_auth: urlIsCanvas,
          interval_hours: 24,
        });
        addLog(`${new Date().toLocaleTimeString()}  ${t("new.logAutoScrapeEnabled")}`, "text-success");
      } catch (scrapeSourceErr) {
        addLog(`${new Date().toLocaleTimeString()}  Auto-scrape setup: ${(scrapeSourceErr as Error).message}`, "text-warning");
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
    } catch (err) {
      const errMsg = (err as Error).message;
      addLog(`${new Date().toLocaleTimeString()}  ${t("new.logScrapeFailed")}: ${errMsg}`, "text-destructive");
      if (urlIsCanvas && errMsg.includes("authentication")) {
        addLog(`${new Date().toLocaleTimeString()}  ${t("new.logAuthTip")}`, "text-warning");
      }
    }
  }

  return true;
}

/**
 * Builds the CourseMetadata object used during creation and workspace entry.
 */
export function buildMetadata(
  features: Record<string, boolean>,
  autoScrape: boolean,
  url: string,
  mode: Mode,
): CourseMetadata {
  return {
    workspace_features: features,
    auto_scrape: {
      enabled: Boolean(autoScrape && url.trim() && (mode === "url" || mode === "both")),
      interval_hours: 24,
    },
  };
}
