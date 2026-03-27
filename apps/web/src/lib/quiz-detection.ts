export interface GeneratedQuizDraft {
  rawContent: string;
  questionCount: number;
}

export interface GeneratedQuizDetectionResult {
  draft: GeneratedQuizDraft | null;
  error: string | null;
}

function stripCodeFences(text: string): string {
  const trimmed = text.trim();
  if (!trimmed.startsWith("```")) {
    return trimmed;
  }
  const withoutOpen = trimmed.includes("\n") ? trimmed.split("\n").slice(1).join("\n") : trimmed.slice(3);
  return withoutOpen.endsWith("```") ? withoutOpen.slice(0, -3).trim() : withoutOpen.trim();
}

function parseLlmJson(text: string): unknown {
  const cleaned = stripCodeFences(text);
  try {
    return JSON.parse(cleaned);
  } catch {
    // fall through
  }

  const arrayStart = text.indexOf("[");
  const arrayEnd = text.lastIndexOf("]");
  if (arrayStart >= 0 && arrayEnd > arrayStart) {
    try {
      return JSON.parse(text.slice(arrayStart, arrayEnd + 1));
    } catch {
      // fall through
    }
  }

  const objectStart = text.indexOf("{");
  const objectEnd = text.lastIndexOf("}");
  if (objectStart >= 0 && objectEnd > objectStart) {
    try {
      return JSON.parse(text.slice(objectStart, objectEnd + 1));
    } catch {
      return null;
    }
  }

  return null;
}

function asQuestionArray(value: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(value)) {
    return value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object");
  }
  if (value && typeof value === "object") {
    return [value as Record<string, unknown>];
  }
  return [];
}

function validateQuestion(question: Record<string, unknown>, index: number): string | null {
  const questionType = String(question.question_type ?? "").trim();
  const prompt = String(question.question ?? "").trim();
  const correctAnswer = String(question.correct_answer ?? "").trim();
  const explanation = String(question.explanation ?? "").trim();

  if (!questionType) return `Question ${index + 1} is missing question_type.`;
  if (!prompt) return `Question ${index + 1} is missing question text.`;
  if (!correctAnswer) return `Question ${index + 1} is missing correct_answer.`;
  if (!explanation) return `Question ${index + 1} is missing explanation.`;

  if (questionType === "mc") {
    const options = question.options;
    if (!options || typeof options !== "object" || Array.isArray(options)) {
      return `Question ${index + 1} needs a valid options map.`;
    }
    if (Object.keys(options).length < 4) {
      return `Question ${index + 1} needs 4 multiple-choice options.`;
    }
  }

  return null;
}

export function detectGeneratedQuizDraft(text: string): GeneratedQuizDetectionResult {
  const parsed = parseLlmJson(text);
  const questions = asQuestionArray(parsed);
  if (questions.length === 0) {
    return { draft: null, error: null };
  }

  for (const [index, question] of questions.entries()) {
    const error = validateQuestion(question, index);
    if (error) {
      return { draft: null, error };
    }
  }

  return {
    draft: {
      rawContent: text,
      questionCount: questions.length,
    },
    error: null,
  };
}
