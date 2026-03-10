"""Cold-start layout computation — maps document type to an initial block layout.

When a user uploads their first document, this module computes a sensible
default layout based on the document classification and LOOM concept count.
"""

from __future__ import annotations

# Document type -> layout mapping
DOC_TYPE_LAYOUT: dict[str, dict] = {
    "textbook": {
        "mode": "course_following",
        "blocks": ["notes", "quiz", "progress", "flashcards"],
        "primary": "notes",
    },
    "lecture_slides": {
        "mode": "course_following",
        "blocks": ["notes", "flashcards", "quiz", "progress"],
        "primary": "notes",
    },
    "assignment": {
        "mode": "exam_prep",
        "blocks": ["notes", "quiz", "progress"],
        "primary": "quiz",
    },
    "exam_schedule": {
        "mode": "exam_prep",
        "blocks": ["quiz", "flashcards", "progress"],
        "primary": "quiz",
    },
    "syllabus": {
        "mode": "course_following",
        "blocks": ["notes", "progress"],
        "primary": "notes",
    },
    "notes": {
        "mode": "self_paced",
        "blocks": ["notes", "flashcards", "progress"],
        "primary": "notes",
    },
    "other": {
        "mode": "self_paced",
        "blocks": ["notes", "quiz", "flashcards", "progress"],
        "primary": "notes",
    },
}


def compute_cold_start_layout(
    doc_category: str,
    loom_concept_count: int = 0,
) -> dict:
    """Compute a cold-start block layout from document classification.

    Returns a dict with keys: mode, blocks (list of block specs), cold_start.
    """
    spec = DOC_TYPE_LAYOUT.get(doc_category, DOC_TYPE_LAYOUT["other"])
    blocks = []
    for i, bt in enumerate(spec["blocks"]):
        size = "large" if bt == spec["primary"] else ("medium" if i < 2 else "small")
        blocks.append({"type": bt, "size": size, "source": "template"})

    # If LOOM extracted enough concepts, add knowledge_graph
    if loom_concept_count >= 5 and "knowledge_graph" not in spec["blocks"]:
        blocks.append({"type": "knowledge_graph", "size": "medium", "source": "agent"})

    return {
        "mode": spec["mode"],
        "blocks": blocks,
        "columns": 2,
        "templateId": None,
        "cold_start": True,
    }
