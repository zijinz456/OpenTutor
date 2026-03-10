"""LOOM — Learner-Oriented Ontology Memory.

Implements the core LOOM pattern (arxiv:2511.21037):
1. Extract concepts from course content via LLM
2. Build a prerequisite/relationship graph
3. Track per-user concept mastery
4. Provide concept recommendations (what to study next)

This module re-exports all public functions for backward compatibility.
Implementation is split across:
  - loom_extraction.py — concept extraction from content
  - loom_mastery.py   — mastery tracking and FIRe propagation
  - loom_graph.py     — graph queries, learning paths, cross-course linking

Usage:
    from services.loom import extract_course_concepts, update_concept_mastery, get_mastery_graph

    # After ingestion: extract concepts from content
    await extract_course_concepts(db, course_id)

    # After quiz/practice: update mastery
    await update_concept_mastery(db, user_id, concept_name, course_id, correct=True)

    # For the tutor: get mastery-colored concept graph
    graph = await get_mastery_graph(db, user_id, course_id)
"""

from services.loom_extraction import (  # noqa: F401
    extract_course_concepts,
    _BLOOM_LEVELS,
    _EXTRACT_PROMPT,
)

from services.loom_mastery import (  # noqa: F401
    update_concept_mastery,
)

from services.loom_graph import (  # noqa: F401
    get_mastery_graph,
    check_prerequisite_gaps,
    generate_learning_path,
    build_course_graph,
    link_cross_course_concepts,
)

__all__ = [
    "extract_course_concepts",
    "update_concept_mastery",
    "get_mastery_graph",
    "check_prerequisite_gaps",
    "generate_learning_path",
    "build_course_graph",
    "link_cross_course_concepts",
    "_BLOOM_LEVELS",
    "_EXTRACT_PROMPT",
]
