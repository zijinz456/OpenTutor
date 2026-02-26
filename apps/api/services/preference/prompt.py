"""System Prompt preference injection template.

Converts resolved preferences into natural-language instructions
injected into the LLM system prompt.
"""

PREFERENCE_TEMPLATES: dict[str, str] = {
    "note_format": "Format notes as {value} (e.g., bullet points, tables, mind maps).",
    "detail_level": "Use a {value} level of detail in explanations.",
    "language": "Respond in {value}.",
    "explanation_style": "Explain concepts using a {value} approach.",
    "quiz_difficulty": "Set quiz difficulty to {value}.",
    "visual_preference": "For visualizations, prefer {value} format.",
}


def build_preference_prompt(preferences: dict[str, str]) -> str:
    """Convert resolved preferences dict into system prompt instructions."""
    lines = []
    for dimension, value in preferences.items():
        template = PREFERENCE_TEMPLATES.get(dimension)
        if template:
            lines.append(template.format(value=value))
        else:
            lines.append(f"User preference for {dimension}: {value}.")

    if not lines:
        return ""

    return "## User Preferences\n" + "\n".join(f"- {line}" for line in lines)
