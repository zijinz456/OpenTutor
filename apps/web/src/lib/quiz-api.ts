/**
 * Quiz API client functions.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export interface QuizProblem {
  id: string;
  question_type: string;
  question: string;
  options: Record<string, string> | null;
  order_index: number;
}

export interface AnswerResult {
  is_correct: boolean;
  correct_answer: string | null;
  explanation: string | null;
}

export async function listProblems(courseId: string): Promise<QuizProblem[]> {
  const res = await fetch(`${API_BASE}/quiz/${courseId}`);
  if (!res.ok) throw new Error("Failed to load problems");
  return res.json();
}

export async function extractQuiz(courseId: string): Promise<{ problems_created: number }> {
  const res = await fetch(`${API_BASE}/quiz/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course_id: courseId }),
  });
  if (!res.ok) throw new Error("Quiz extraction failed");
  return res.json();
}

export async function submitAnswer(problemId: string, answer: string): Promise<AnswerResult> {
  const res = await fetch(`${API_BASE}/quiz/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ problem_id: problemId, user_answer: answer }),
  });
  if (!res.ok) throw new Error("Answer submission failed");
  return res.json();
}
