import { describe, expect, it } from "vitest";
import type { CourseProgress, StudyGoal } from "@/lib/api";
import {
  buildGoalDeadlineSnapshots,
  evaluateModeSuggestion,
} from "./mode-recommendations";

function makeGoal(overrides: Partial<StudyGoal>): StudyGoal {
  return {
    id: "goal-1",
    user_id: "user-1",
    course_id: "course-1",
    title: "Midterm",
    objective: "Study",
    success_metric: null,
    current_milestone: null,
    next_action: null,
    status: "active",
    confidence: null,
    target_date: null,
    metadata_json: null,
    linked_task_count: 0,
    created_at: null,
    updated_at: null,
    completed_at: null,
    ...overrides,
  };
}

function makeProgress(overrides: Partial<CourseProgress>): CourseProgress {
  return {
    course_id: "course-1",
    total_nodes: 10,
    mastered: 6,
    reviewed: 4,
    in_progress: 2,
    not_started: 0,
    total_study_minutes: 120,
    average_mastery: 0.72,
    completion_percent: 60,
    gap_type_breakdown: {},
    ...overrides,
  };
}

const t = (key: string) => key;
const tf = (key: string, values: Record<string, string | number>) =>
  `${key}:${JSON.stringify(values)}`;

describe("mode recommendations", () => {
  it("builds deadline snapshots from active goals", () => {
    const now = new Date("2026-03-30T00:00:00.000Z").getTime();
    const deadlines = buildGoalDeadlineSnapshots([
      makeGoal({ title: "Essay", target_date: "2026-04-02T00:00:00.000Z" }),
      makeGoal({ id: "goal-2", title: "No date", target_date: null }),
    ], now);

    expect(deadlines).toHaveLength(1);
    expect(deadlines[0].goal.title).toBe("Essay");
    expect(deadlines[0].daysLeft).toBe(3);
  });

  it("prefers error-rate recommendation over plain deadline", () => {
    const now = new Date("2026-03-30T00:00:00.000Z").getTime();
    const deadlines = buildGoalDeadlineSnapshots([
      makeGoal({ target_date: "2026-04-01T00:00:00.000Z" }),
    ], now);
    const suggestion = evaluateModeSuggestion({
      currentMode: "course_following",
      deadlines,
      progress: makeProgress({
        average_mastery: 0.5,
        mastered: 2,
        reviewed: 3,
        in_progress: 6,
      }),
      t,
      tf,
    });

    expect(suggestion?.recommendationKey).toBe("error_rate");
    expect(suggestion?.suggestedMode).toBe("exam_prep");
  });

  it("suggests maintenance after all exam deadlines have passed", () => {
    const now = new Date("2026-03-30T00:00:00.000Z").getTime();
    const deadlines = buildGoalDeadlineSnapshots([
      makeGoal({ target_date: "2026-03-20T00:00:00.000Z" }),
    ], now);
    const suggestion = evaluateModeSuggestion({
      currentMode: "exam_prep",
      deadlines,
      progress: makeProgress({ average_mastery: 0.9 }),
      t,
      tf,
    });

    expect(suggestion?.recommendationKey).toBe("exam_passed");
    expect(suggestion?.suggestedMode).toBe("maintenance");
  });

  it("suggests maintenance for high mastery without near deadline", () => {
    const suggestion = evaluateModeSuggestion({
      currentMode: "self_paced",
      deadlines: [],
      progress: makeProgress({
        average_mastery: 0.91,
        mastered: 8,
        reviewed: 4,
        in_progress: 1,
      }),
      t,
      tf,
    });

    expect(suggestion?.recommendationKey).toBe("mastery");
    expect(suggestion?.suggestedMode).toBe("maintenance");
  });
});
