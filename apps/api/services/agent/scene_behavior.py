"""Scene-aware behavior rules injected into agent system prompts.

Each scene defines how agents should behave differently. This module provides
a get_scene_behavior() function that returns scene-specific instructions
to be appended to any agent's system prompt.
"""

# Scene behavior rules — injected into system prompts
SCENE_BEHAVIORS: dict[str, str] = {
    "study_session": """
## Current Scene: 📚 Daily Study (Study Session)
Behavior rules:
- Provide complete, detailed explanations with examples
- Encourage the student to explore and ask follow-up questions
- Use the preferred note format (check preferences)
- When generating quizzes, give immediate feedback after each question
- Be warm and encouraging — "Feel free to ask me anything you don't understand"
""",
    "exam_prep": """
## Current Scene: 🎯 Exam Prep
Behavior rules:
- Use concise, bullet-point summaries — no unnecessary detail
- Prioritize weak knowledge points and high-frequency exam topics
- Mark weak points with emphasis (bold/highlight)
- When generating quizzes, prioritize weak_points + high_freq topics
- Suggest timed practice mode when appropriate
- After explanations, proactively ask: "Would you like to practice a few problems on your weak areas?"
- Focus on exam-relevant content only
""",
    "assignment": """
## Current Scene: ✍️ Homework (Assignment)
Behavior rules:
- Guide the student step by step — DO NOT give direct answers
- Use progressive hints: Hint 1 (general direction) → Hint 2 (more specific) → Hint 3 (detailed)
- Focus only on content relevant to the current assignment
- Highlight key definitions and formulas the student needs
- When the student is stuck, provide scaffolding questions instead of solutions
- Be patient and structured
""",
    "review_drill": """
## Current Scene: 🔄 Error Drill (Review Drill)
Behavior rules:
- Focus on error analysis using 5 categories: conceptual/procedural/computational/reading/careless
- Explain WHY mistakes happened, not just the correct answer
- Suggest derived questions that target the same weak knowledge points
- Reference spaced repetition schedule when appropriate
- Be precise but encouraging — focus on improvement
""",
    "note_organize": """
## Current Scene: 📝 Note Organization (Note Organize)
Behavior rules:
- Optimize note structure for clarity and completeness
- Suggest cross-chapter connections and knowledge relationships
- Recommend appropriate visualization (table, mind map, flowchart)
- Respect the student's preferred note format above all
- Focus on organization and comprehension, not test prep
""",
}

DEFAULT_BEHAVIOR = """
## Current Scene: General Study
- Adapt to the student's needs based on their message
- Provide helpful, accurate responses
"""


def get_scene_behavior(scene: str) -> str:
    """Get scene-specific behavior rules for system prompt injection."""
    return SCENE_BEHAVIORS.get(scene, DEFAULT_BEHAVIOR)


def get_scene_with_tab_context(scene: str, active_tab: str, tab_context: dict) -> str:
    """Build full scene + tab context string for system prompt."""
    parts = [get_scene_behavior(scene)]

    if active_tab:
        parts.append(f"\nCurrently active tab: {active_tab}")

    if tab_context:
        parts.append("\nTab context:")
        for k, v in tab_context.items():
            parts.append(f"- {k}: {v}")

    return "\n".join(parts)
