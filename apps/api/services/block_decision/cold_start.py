"""Cold-start layout computation — maps document type to an initial block layout.

When a user uploads their first document, this module computes a sensible
default layout based on the document classification and LOOM concept count.

LECTOR integration: avoids surfacing review blocks until the student has
enough practice data for meaningful LECTOR prioritization.
"""

from __future__ import annotations

# Document type -> layout mapping
DOC_TYPE_LAYOUT: dict[str, dict] = {
    "textbook": {
        "mode": "course_following",
        "blocks": ["chapter_list", "notes", "quiz", "flashcards"],
        "primary": "notes",
    },
    "lecture_slides": {
        "mode": "course_following",
        "blocks": ["chapter_list", "notes", "flashcards", "quiz"],
        "primary": "notes",
    },
    "assignment": {
        "mode": "exam_prep",
        "blocks": ["notes", "quiz"],
        "primary": "quiz",
    },
    "exam_schedule": {
        "mode": "exam_prep",
        "blocks": ["quiz", "flashcards"],
        "primary": "quiz",
    },
    "syllabus": {
        "mode": "course_following",
        "blocks": ["chapter_list", "notes"],
        "primary": "notes",
    },
    "notes": {
        "mode": "self_paced",
        "blocks": ["notes", "flashcards"],
        "primary": "notes",
    },
    "other": {
        "mode": "self_paced",
        "blocks": ["chapter_list", "notes", "quiz", "flashcards"],
        "primary": "notes",
    },
}

# Minimum practice attempts before LECTOR can generate meaningful review sessions
LECTOR_MIN_PRACTICE = 5


def compute_cold_start_layout(
    doc_category: str,
    loom_concept_count: int = 0,
    practice_count: int = 0,
) -> dict:
    """Compute a cold-start block layout from document classification.

    Parameters
    ----------
    doc_category : str
        Document classification (textbook, lecture_slides, etc.)
    loom_concept_count : int
        Number of concepts extracted by LOOM
    practice_count : int
        Number of practice attempts the student has completed for this course

    Returns a dict with keys: mode, blocks (list of block specs), cold_start.
    """
    spec = DOC_TYPE_LAYOUT.get(doc_category, DOC_TYPE_LAYOUT["other"])
    blocks = []
    for i, bt in enumerate(spec["blocks"]):
        size = "large" if bt == spec["primary"] else ("medium" if i < 2 else "small")
        blocks.append({"type": bt, "size": size, "source": "template"})

    # If LOOM extracted enough concepts, add knowledge_graph for concept overview
    if loom_concept_count >= 5 and "knowledge_graph" not in spec["blocks"]:
        blocks.append({"type": "knowledge_graph", "size": "medium", "source": "agent"})

    # Rich concept graph (10+) without practice: emphasize quiz to build baseline
    if loom_concept_count >= 10 and practice_count < LECTOR_MIN_PRACTICE:
        # Promote quiz to large if it isn't primary
        for block in blocks:
            if block["type"] == "quiz" and block["size"] == "small":
                block["size"] = "medium"

    # Only add review block once student has enough practice for LECTOR
    if practice_count >= LECTOR_MIN_PRACTICE:
        if "review" not in [b["type"] for b in blocks]:
            blocks.append({"type": "review", "size": "medium", "source": "agent"})

    return {
        "mode": spec["mode"],
        "blocks": blocks,
        "columns": 2,
        "templateId": None,
        "cold_start": True,
    }
