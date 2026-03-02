"use client";

interface StatusBarProps {
  courseName: string;
  chapterName?: string;
  practiceProgress?: string;
  studyTime?: string;
  activeGoalTitle?: string | null;
  activeTaskTitle?: string | null;
  sceneLabel?: string | null;
  nextActionTitle?: string | null;
}

/**
 * StatusBar is intentionally empty -- its information is now shown
 * in the breadcrumb bar and the collapsible AgentFocusStrip.
 * The export is kept so existing imports don't break during migration.
 */
export function StatusBar(_props: StatusBarProps) {
  void _props;
  return null;
}
