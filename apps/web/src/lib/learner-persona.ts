/**
 * Learner's Persona — persistent cross-session memory for the agent.
 * Tracks learning preferences, behavior patterns, and study rhythm.
 * Stored in localStorage for local-first data ownership.
 */

export interface LearnerPersona {
  /** Preferred note format (step_by_step, summary, mind_map, table). */
  noteFormat: string;
  /** Preferred explanation style (detailed, concise, visual). */
  explanationStyle: string;
  /** Difficulty preference (easy, adaptive, hard). */
  difficultyPreference: string;
  /** Study session times (ISO day-of-week + hour). */
  studyTimes: Array<{ dayOfWeek: number; hour: number; count: number }>;
  /** Average session duration in minutes. */
  avgSessionMinutes: number;
  /** Topics that took extra time (sticking points). */
  stickingPoints: string[];
  /** Subjects studied together (cross-course patterns). */
  crossCoursePatterns: string[];
  /** Total sessions tracked. */
  totalSessions: number;
  /** Last session timestamp. */
  lastSessionAt: string | null;
  /** Preferred language (en, zh, auto). */
  preferredLanguage: string;
}

const PERSONA_KEY = "opentutor_learner_persona";

const DEFAULT_PERSONA: LearnerPersona = {
  noteFormat: "auto",
  explanationStyle: "balanced",
  difficultyPreference: "adaptive",
  studyTimes: [],
  avgSessionMinutes: 0,
  stickingPoints: [],
  crossCoursePatterns: [],
  totalSessions: 0,
  lastSessionAt: null,
  preferredLanguage: "auto",
};

export function getPersona(): LearnerPersona {
  if (typeof window === "undefined") return DEFAULT_PERSONA;
  try {
    const raw = localStorage.getItem(PERSONA_KEY);
    if (raw) return { ...DEFAULT_PERSONA, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return DEFAULT_PERSONA;
}

export function updatePersona(updates: Partial<LearnerPersona>): void {
  if (typeof window === "undefined") return;
  try {
    const current = getPersona();
    const merged = { ...current, ...updates };
    localStorage.setItem(PERSONA_KEY, JSON.stringify(merged));
  } catch { /* ignore */ }
}

/**
 * Record a study session visit — updates study time patterns and session count.
 */
export function recordSessionVisit(): void {
  const now = new Date();
  const persona = getPersona();

  // Update study times histogram
  const dayOfWeek = now.getDay();
  const hour = now.getHours();
  const existingSlot = persona.studyTimes.find(
    (s) => s.dayOfWeek === dayOfWeek && s.hour === hour,
  );
  if (existingSlot) {
    existingSlot.count += 1;
  } else {
    persona.studyTimes.push({ dayOfWeek, hour, count: 1 });
  }

  // Keep only top 20 study time slots
  persona.studyTimes.sort((a, b) => b.count - a.count);
  persona.studyTimes = persona.studyTimes.slice(0, 20);

  persona.totalSessions += 1;
  persona.lastSessionAt = now.toISOString();

  updatePersona(persona);
}

/**
 * Get the optimal study window based on past behavior.
 * Returns the top 3 most frequent day+hour combinations.
 */
export function getOptimalStudyWindows(): Array<{ dayOfWeek: number; hour: number; count: number }> {
  const persona = getPersona();
  return persona.studyTimes.slice(0, 3);
}

/**
 * Format a study window for display.
 */
export function formatStudyWindow(window: { dayOfWeek: number; hour: number }): string {
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const h = window.hour;
  const period = h >= 12 ? "PM" : "AM";
  const displayHour = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${days[window.dayOfWeek]} ${displayHour}${period}`;
}
