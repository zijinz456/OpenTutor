import { useCallback, useEffect, useState } from "react";
import {
  getNextAction,
  listAgentTasks,
  listChatSessions,
  listIngestionJobs,
  listPreferenceSignals,
  listStudyGoals,
  type AgentTask,
  type ChatSessionSummary,
  type IngestionJobSummary,
  type NextActionResponse,
  type PreferenceSignal,
  type StudyGoal,
} from "@/lib/api";

interface ActivityData {
  tasks: AgentTask[];
  goals: StudyGoal[];
  jobs: IngestionJobSummary[];
  sessions: ChatSessionSummary[];
  signals: PreferenceSignal[];
  nextAction: NextActionResponse | null;
}

const EMPTY: ActivityData = {
  tasks: [],
  goals: [],
  jobs: [],
  sessions: [],
  signals: [],
  nextAction: null,
};

/**
 * Polls activity data for a course with visibility-aware start/stop.
 * Returns the latest data and a `refresh` function for manual re-fetching.
 */
export function useActivityPolling(courseId: string, intervalMs = 5000) {
  const [data, setData] = useState<ActivityData>(EMPTY);

  const refresh = useCallback(async () => {
    const [tasks, goals, jobs, sessions, signals, nextAction] = await Promise.all([
      listAgentTasks(courseId),
      listStudyGoals(courseId),
      listIngestionJobs(courseId),
      listChatSessions(courseId),
      listPreferenceSignals(courseId),
      getNextAction(courseId).catch(() => null),
    ]);
    setData({
      tasks,
      goals,
      jobs,
      sessions: sessions.slice(0, 5),
      signals: signals.slice(0, 5),
      nextAction,
    });
  }, [courseId]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const load = async () => {
      try {
        await refresh();
      } catch {
        if (cancelled) return;
        setData(EMPTY);
      }
    };

    const startPolling = () => {
      if (timer) return;
      void load();
      timer = window.setInterval(() => void load(), intervalMs);
    };

    const stopPolling = () => {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    };

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        startPolling();
      } else {
        stopPolling();
      }
    };

    startPolling();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refresh, intervalMs]);

  return { ...data, refresh };
}
