from __future__ import annotations

"""Quiz extraction service.

Extracts practice problems from content using structured LLM output and writes
consistent problem metadata for downstream review, assessment, and mastery
tracking. The metadata schema is generic learning analytics, not domain-specific.
"""

import uuid

from models.practice import PracticeProblem
from services.llm.router import get_llm_client
from services.practice.annotation import build_practice_problem, normalize_problem_annotation, parse_question_array

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
6. For EACH question, provide structured learning metadata:
   - difficulty_layer: 1 basic understanding, 2 standard application, 3 advanced/tricky transfer
   - core_concept: the main concept being tested
   - bloom_level: remember | understand | apply | analyze | evaluate | create
   - potential_traps: specific misconceptions or pitfalls (empty list if none)
   - layer_justification: one short reason for the difficulty_layer choice
   - skill_focus: what ability is being tested (for example recall, comparison, derivation, interpretation)
   - source_section: the section title if obvious from context

Output ONLY a valid JSON array with this structure:
```json
[
  {
    "question_type": "mc",
    "question": "What is the primary purpose of...?",
    "options": {"A": "Option 1", "B": "Option 2", "C": "Option 3", "D": "Option 4"},
    "correct_answer": "B",
    "explanation": "Option B is correct because...",
    "difficulty_layer": 2,
    "problem_metadata": {
      "core_concept": "main idea",
      "bloom_level": "apply",
      "potential_traps": ["common confusion 1"],
      "layer_justification": "Requires applying the idea to a new example",
      "skill_focus": "application",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "tf",
    "question": "The process of X always results in Y.",
    "options": null,
    "correct_answer": "False",
    "explanation": "This is false because...",
    "difficulty_layer": 1,
    "problem_metadata": {
      "core_concept": "X versus Y",
      "bloom_level": "understand",
      "potential_traps": [],
      "layer_justification": "Direct comprehension check",
      "skill_focus": "concept check",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "short_answer",
    "question": "Explain the difference between X and Y.",
    "options": null,
    "correct_answer": "X differs from Y in that...",
    "explanation": "The key distinction is...",
    "difficulty_layer": 2,
    "problem_metadata": {
      "core_concept": "difference between X and Y",
      "bloom_level": "analyze",
      "potential_traps": ["mixing the definitions"],
      "layer_justification": "Requires comparison rather than recall",
      "skill_focus": "comparison",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "fill_blank",
    "question": "The _____ algorithm is used for finding shortest paths.",
    "options": null,
    "correct_answer": "Dijkstra's",
    "explanation": "Dijkstra's algorithm...",
    "difficulty_layer": 1,
    "problem_metadata": {
      "core_concept": "shortest path algorithms",
      "bloom_level": "remember",
      "potential_traps": [],
      "layer_justification": "Direct recall of a named algorithm",
      "skill_focus": "recall",
      "source_section": "Section title"
    }
  }
]
```

IMPORTANT: Output ONLY the JSON array, no other text."""
def _normalize_problem_metadata(
    question: dict,
    *,
    title: str,
) -> tuple[int | None, dict]:
    normalized = normalize_problem_annotation(question, title=title, source="extracted")
    return normalized["difficulty_layer"], normalized["problem_metadata"]


_MODE_QUIZ_HINTS: dict[str, str] = {
    "exam_prep": "\n\nMode: EXAM PREP — Bias toward Layer 2-3 difficulty. Include time estimates per question. Prefer application and analysis questions.",
    "maintenance": "\n\nMode: MAINTENANCE — Only generate questions about previously-covered core concepts. Focus on retention and recall.",
    "self_paced": "\n\nMode: SELF-PACED — Include open-ended and cross-topic questions. Encourage deeper exploration.",
    "course_following": "\n\nMode: COURSE FOLLOWING — Strictly follow the provided content. Only test concepts explicitly covered in the material.",
}

_DIFFICULTY_HINTS: dict[str, str] = {
    "easy": "\n\nDifficulty: EASY — Mostly Layer 1-2 questions. Focus on core definitions and basic checks.",
    "medium": "\n\nDifficulty: MEDIUM — Balanced Layer 1-3 mix. Emphasize applied understanding.",
    "hard": "\n\nDifficulty: HARD — Bias strongly toward Layer 2-3. Include tricky distractors and transfer scenarios.",
}


async def extract_questions(
    content: str,
    title: str,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
    mode: str | None = None,
    difficulty: str | None = None,
) -> list:
    """Extract practice questions from content using LLM.

    Args:
        content: Text content to generate questions from
        title: Section title for context
        course_id: Course UUID
        content_node_id: Optional reference to content tree node
        mode: Learning mode hint for question generation style

    Returns:
        List of PracticeProblem ORM objects ready for DB insertion
    """
    client = get_llm_client()

    user_msg = f"## {title}\n\n{content}"
    if mode and mode in _MODE_QUIZ_HINTS:
        user_msg += _MODE_QUIZ_HINTS[mode]
    if difficulty and difficulty in _DIFFICULTY_HINTS:
        user_msg += _DIFFICULTY_HINTS[difficulty]

    response, _ = await client.chat(
        EXTRACTION_PROMPT,
        user_msg,
    )

    questions = parse_question_array(response)
    if not questions:
        return []

    # Convert to PracticeProblem models
    problems = []
    for i, q in enumerate(questions):
        problem = build_practice_problem(
            course_id=course_id,
            content_node_id=content_node_id,
            title=title,
            question=q,
            order_index=i,
            source="extracted",
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
