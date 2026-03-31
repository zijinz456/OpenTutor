import type { WrongAnswer, ReviewItem } from "@/lib/api";

export type TranslateFn = (key: string) => string;

export function matchesFocus(text: string | null | undefined, terms: string[]): boolean {
  if (!text || terms.length === 0) return false;
  const lower = text.toLowerCase();
  return terms.some((term) => lower.includes(term));
}

export function scoreWrongAnswerFocus(item: WrongAnswer, terms: string[]): number {
  if (terms.length === 0) return 0;
  const question = (item.question ?? "").toLowerCase();
  const diagnosis = (item.diagnosis ?? "").toLowerCase();
  const knowledgePoints = (item.knowledge_points ?? []).map((point) => point.toLowerCase());

  let score = 0;
  for (const term of terms) {
    if (question.includes(term)) score += 2;
    if (diagnosis.includes(term)) score += 1;
    for (const point of knowledgePoints) {
      if (point.includes(term) || term.includes(point)) {
        score += 3;
        break;
      }
    }
  }
  return score;
}

export interface RankedSignal {
  label: string;
  count: number;
}

export interface ErrorPatternSummary {
  diagnoses: RankedSignal[];
  categories: RankedSignal[];
  knowledgePoints: RankedSignal[];
}

export interface MasterySummary {
  avgMastery: number;
  avgRetrievability: number;
  urgent: number;
  warning: number;
  stale: number;
}

export interface ErrorTrendSummary {
  recent7d: number;
  previous7d: number;
  delta: number;
  direction: "up" | "down" | "flat";
}

export type QuizDifficulty = "easy" | "medium" | "hard";

export interface DifficultyRecommendation {
  level: QuizDifficulty;
  reasonKey: string;
}

function toDisplayLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = value.trim();
  if (!normalized) return null;
  return normalized.replace(/_/g, " ");
}

function rankSignals(counter: Map<string, number>, limit = 5): RankedSignal[] {
  return [...counter.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([label, count]) => ({ label, count }));
}

export function buildErrorPatternSummary(items: WrongAnswer[]): ErrorPatternSummary {
  const diagnosisCounter = new Map<string, number>();
  const categoryCounter = new Map<string, number>();
  const pointCounter = new Map<string, number>();

  for (const item of items) {
    const diagnosis = toDisplayLabel(item.diagnosis ?? item.error_detail?.diagnosis);
    if (diagnosis) diagnosisCounter.set(diagnosis, (diagnosisCounter.get(diagnosis) ?? 0) + 1);

    const category = toDisplayLabel(item.error_category ?? item.error_detail?.category);
    if (category) categoryCounter.set(category, (categoryCounter.get(category) ?? 0) + 1);

    for (const point of item.knowledge_points ?? []) {
      const label = toDisplayLabel(point);
      if (!label) continue;
      pointCounter.set(label, (pointCounter.get(label) ?? 0) + 1);
    }
  }

  return {
    diagnoses: rankSignals(diagnosisCounter),
    categories: rankSignals(categoryCounter),
    knowledgePoints: rankSignals(pointCounter),
  };
}

export function buildMasterySummary(items: ReviewItem[]): MasterySummary {
  if (items.length === 0) {
    return {
      avgMastery: 0,
      avgRetrievability: 0,
      urgent: 0,
      warning: 0,
      stale: 0,
    };
  }

  const now = Date.now();
  const avgMastery = Math.round(
    (items.reduce((sum, item) => sum + (item.mastery ?? 0), 0) / items.length) * 100,
  );
  const avgRetrievability = Math.round(
    (items.reduce((sum, item) => sum + (item.retrievability ?? 0), 0) / items.length) * 100,
  );
  const urgent = items.filter((item) => item.urgency === "urgent" || item.urgency === "overdue").length;
  const warning = items.filter((item) => item.urgency === "warning").length;
  const stale = items.filter((item) => {
    if (!item.last_reviewed) return true;
    const last = new Date(item.last_reviewed).getTime();
    if (Number.isNaN(last)) return true;
    return now - last > 14 * 24 * 60 * 60 * 1000;
  }).length;

  return { avgMastery, avgRetrievability, urgent, warning, stale };
}

export function buildErrorTrendSummary(items: WrongAnswer[]): ErrorTrendSummary {
  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  let recent7d = 0;
  let previous7d = 0;

  for (const item of items) {
    if (!item.created_at) continue;
    const ts = new Date(item.created_at).getTime();
    if (Number.isNaN(ts)) continue;
    const ageMs = now - ts;
    if (ageMs < 0) continue;
    if (ageMs <= 7 * dayMs) recent7d += 1;
    else if (ageMs <= 14 * dayMs) previous7d += 1;
  }

  const delta = recent7d - previous7d;
  const direction: ErrorTrendSummary["direction"] =
    delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return { recent7d, previous7d, delta, direction };
}

export function recommendQuizDifficulty(
  mastery: MasterySummary,
  trend: ErrorTrendSummary,
  wrongCount: number,
): DifficultyRecommendation {
  if (mastery.avgMastery < 55 || mastery.urgent >= 3 || trend.delta >= 2 || wrongCount >= 8) {
    return { level: "easy", reasonKey: "unit.difficulty.reason.recovery" };
  }
  if (mastery.avgMastery < 80 || mastery.warning >= 2 || trend.delta > 0 || wrongCount >= 4) {
    return { level: "medium", reasonKey: "unit.difficulty.reason.balanced" };
  }
  return { level: "hard", reasonKey: "unit.difficulty.reason.challenge" };
}

export function modeHintFromDifficulty(level: QuizDifficulty): "course_following" | "self_paced" | "exam_prep" {
  if (level === "hard") return "exam_prep";
  if (level === "easy") return "course_following";
  return "self_paced";
}
