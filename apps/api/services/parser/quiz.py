"""Quiz extraction service.

Extracts practice problems from content using LLM structured output.
Supports 7 question types per Obsidian Quiz Generator pattern.

Reference: ECuiDev/obsidian-quiz-generator — 7 question type prompts
Reference: raunakwete43/QuizCrafter — FastAPI+React pipeline
"""

import json
import uuid

from models.practice import PracticeProblem
from services.llm.router import get_llm_client

# 7 question types (from Obsidian Quiz Generator)
QUESTION_TYPES = {
    "mc": "Multiple Choice — one correct answer from 4 options",
    "tf": "True/False — statement is true or false",
    "short_answer": "Short Answer — brief text response",
    "fill_blank": "Fill in the Blank — complete the sentence",
    "matching": "Matching — match items from two columns",
    "select_all": "Select All That Apply — multiple correct answers",
    "free_response": "Free Response — extended written answer",
}

EXTRACTION_PROMPT = """You are an expert educator creating practice questions from learning materials.

Given the content below, extract or generate practice questions. Follow these rules:

1. Generate a mix of question types: mc (multiple choice), tf (true/false), short_answer, fill_blank
2. Each question should test understanding, not just recall
3. For multiple choice, always provide exactly 4 options (A, B, C, D)
4. Include the correct answer and a brief explanation
5. Generate 3-8 questions depending on content length and complexity

Output ONLY a valid JSON array with this structure:
```json
[
  {
    "question_type": "mc",
    "question": "What is the primary purpose of...?",
    "options": {"A": "Option 1", "B": "Option 2", "C": "Option 3", "D": "Option 4"},
    "correct_answer": "B",
    "explanation": "Option B is correct because..."
  },
  {
    "question_type": "tf",
    "question": "The process of X always results in Y.",
    "options": null,
    "correct_answer": "False",
    "explanation": "This is false because..."
  },
  {
    "question_type": "short_answer",
    "question": "Explain the difference between X and Y.",
    "options": null,
    "correct_answer": "X differs from Y in that...",
    "explanation": "The key distinction is..."
  },
  {
    "question_type": "fill_blank",
    "question": "The _____ algorithm is used for finding shortest paths.",
    "options": null,
    "correct_answer": "Dijkstra's",
    "explanation": "Dijkstra's algorithm..."
  }
]
```

IMPORTANT: Output ONLY the JSON array, no other text."""


async def extract_questions(
    content: str,
    title: str,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
) -> list[PracticeProblem]:
    """Extract practice questions from content using LLM.

    Args:
        content: Text content to generate questions from
        title: Section title for context
        course_id: Course UUID
        content_node_id: Optional reference to content tree node

    Returns:
        List of PracticeProblem ORM objects ready for DB insertion
    """
    client = get_llm_client()

    response, _ = await client.chat(
        EXTRACTION_PROMPT,
        f"## {title}\n\n{content}",
    )

    # Parse JSON from response (handle markdown code blocks)
    json_str = response.strip()
    if json_str.startswith("```"):
        # Strip markdown code block
        lines = json_str.split("\n")
        json_str = "\n".join(lines[1:-1])

    try:
        questions = json.loads(json_str)
    except json.JSONDecodeError:
        # Try to find JSON array in the response
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            questions = json.loads(response[start:end])
        else:
            return []

    # Convert to PracticeProblem models
    problems = []
    for i, q in enumerate(questions):
        problem = PracticeProblem(
            course_id=course_id,
            content_node_id=content_node_id,
            question_type=q.get("question_type", "mc"),
            question=q["question"],
            options=q.get("options"),
            correct_answer=q.get("correct_answer"),
            explanation=q.get("explanation"),
            order_index=i,
        )
        problems.append(problem)

    return problems


async def extract_all_questions(
    nodes: list[dict],
    course_id: uuid.UUID,
) -> list[PracticeProblem]:
    """Extract questions from all content tree nodes that have content."""
    all_problems = []
    for node in nodes:
        if node.get("content") and len(node["content"]) > 100:
            problems = await extract_questions(
                node["content"],
                node["title"],
                course_id,
                content_node_id=node.get("id"),
            )
            all_problems.extend(problems)
    return all_problems
