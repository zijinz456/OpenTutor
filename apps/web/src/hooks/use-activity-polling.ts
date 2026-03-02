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

async function withTimeout<T>(promise: Promise<T>, timeoutMs = 4000): Promise<T> {
  return Promise.race<T>([
    promise,
    new Promise<T>((_, reject) => {
      window.setTimeout(() => reject(new Error("timeout")), timeoutMs);
    }),
  ]);
}

/**
 * Polls activity data for a course with visibility-aware start/stop.
 * Returns the latest data and a `refresh` function for manual re-fetching.
 */
export function useActivityPolling(courseId: string, intervalMs = 5000) {
  const [data, setData] = useState<ActivityData>(EMPTY);

  const refresh = useCallback(async () => {
    const [tasks, goals, jobs, sessions, signals, nextAction] = await Promise.allSettled([
      withTimeout(listAgentTasks(courseId)),
      withTimeout(listStudyGoals(courseId)),
      withTimeout(listIngestionJobs(courseId)),
      withTimeout(listChatSessions(courseId)),
      withTimeout(listPreferenceSignals(courseId)),
      withTimeout(getNextAction(courseId)),
    ]);

    setData((previous) => ({
      tasks: tasks.status === "fulfilled" ? tasks.value : previous.tasks,
      goals: goals.status === "fulfilled" ? goals.value : previous.goals,
      jobs: jobs.status === "fulfilled" ? jobs.value : previous.jobs,
      sessions:
        sessions.status === "fulfilled"
          ? sessions.value.slice(0, 5)
          : previous.sessions,
      signals:
        signals.status === "fulfilled"
          ? signals.value.slice(0, 5)
          : previous.signals,
      nextAction:
        nextAction.status === "fulfilled"
          ? nextAction.value
          : previous.nextAction,
    }));
  }, [courseId]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const load = async () => {
      try {
        await refresh();
      } catch {
        if (cancelled) return;
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
