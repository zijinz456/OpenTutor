"""Seed Juice Shop hacking-lab practice problems (§34.5 Phase 12 T5).

Mirrors ``scripts/seed_code_exercises.py`` — same shape, same container
layout, just a different ``question_type`` and metadata schema.

Usage (from host):
    docker cp scripts/seed_hacking_labs.py   opentutor-api:/tmp/seed_labs.py
    docker cp content/hacking_labs.py        opentutor-api:/tmp/hacking_labs.py
    docker exec opentutor-api python /tmp/seed_labs.py <course_id>

The script imports the ``LABS`` list from ``content/hacking_labs.py``.
No third-party deps — pure stdlib.

Re-seed safety: if a lab with the same ``lab_id`` already exists in the
target course (identified via ``problem_metadata.lab_id``), it is skipped
and logged; we never insert a duplicate.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add repo root (and the script's own dir) to sys.path so ``hacking_labs``
# imports cleanly whether the script runs from the host checkout
# (``content/hacking_labs.py``) or from /tmp inside the api container,
# where the operator copies both files side-by-side.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
for candidate in (_REPO_ROOT, _HERE):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def _load_labs() -> list[dict[str, Any]]:
    """Import the ``LABS`` list from either layout.

    Uses ``importlib`` (not a static ``import``) so the type-checker does
    not need both module paths to exist on the analysis machine — only
    one resolves per environment.
    """
    for module_name in ("content.hacking_labs", "hacking_labs"):
        try:
            mod = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        labs = getattr(mod, "LABS", None)
        if labs is None:
            continue
        return list(labs)
    raise ModuleNotFoundError(
        "could not import LABS from 'content.hacking_labs' or 'hacking_labs'. "
        "Make sure content/hacking_labs.py is importable (repo root on "
        "sys.path) or copy it next to this script in /tmp inside the "
        "container."
    )


LABS: list[dict[str, Any]] = _load_labs()


DIFFICULTY_LAYER: dict[str, int] = {"easy": 1, "medium": 2, "hard": 3}


def _existing_lab_ids(cur: sqlite3.Cursor, course_id: str) -> set[str]:
    """Return the set of ``lab_id`` values already seeded into this course.

    We pull every ``lab_exercise`` row's ``problem_metadata`` JSON and
    extract the ``lab_id`` field. Rows missing that field are ignored
    (they predate this seeder).
    """
    rows = cur.execute(
        """
        SELECT problem_metadata
          FROM practice_problems
         WHERE course_id = ?
           AND question_type = 'lab_exercise'
        """,
        (course_id,),
    ).fetchall()

    ids: set[str] = set()
    for (raw,) in rows:
        if not raw:
            continue
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            continue
        lab_id = meta.get("lab_id")
        if isinstance(lab_id, str):
            ids.add(lab_id)
    return ids


def seed(course_id: str, db_path: str = "/app/data/opentutor.db") -> None:
    """Insert every entry in ``LABS`` into ``practice_problems``.

    Skips entries whose ``id`` is already present in this course (via
    ``problem_metadata.lab_id``) so that re-running the script is a
    no-op for already-seeded labs.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Verify course exists — same guard as seed_code_exercises.py
    course = cur.execute("SELECT name FROM courses WHERE id=?", (course_id,)).fetchone()
    if not course:
        print(f"ERROR: course {course_id} not found", file=sys.stderr)
        sys.exit(1)
    print(f"Seeding into course: {course[0]}")

    already = _existing_lab_ids(cur, course_id)
    if already:
        print(
            f"  (found {len(already)} lab(s) already seeded — "
            f"will skip those: {sorted(already)})"
        )

    # Append after any existing practice_problems in this course
    max_order: int = cur.execute(
        "SELECT COALESCE(MAX(order_index), 0) FROM practice_problems WHERE course_id=?",
        (course_id,),
    ).fetchone()[0]

    now = datetime.now(timezone.utc).isoformat()
    inserted: list[tuple[str, str]] = []
    skipped: list[str] = []
    next_order = max_order

    for lab in LABS:
        lab_id: str = lab["id"]
        if lab_id in already:
            skipped.append(lab_id)
            print(f"  = skip '{lab_id}' (already present)")
            continue

        difficulty: str = lab["difficulty"]
        if difficulty not in DIFFICULTY_LAYER:
            print(
                f"ERROR: lab '{lab_id}' has invalid difficulty "
                f"{difficulty!r}; expected one of "
                f"{sorted(DIFFICULTY_LAYER)}",
                file=sys.stderr,
            )
            sys.exit(2)

        next_order += 1
        pid = str(uuid.uuid4())

        # problem_metadata is the single source of truth for lab-specific
        # fields — the API layer never echoes verification_rubric to the
        # client, it's only read by the server-side grader.
        metadata: dict[str, Any] = {
            "lab_id": lab_id,
            "target_url": lab["target_url"],
            "category": lab["category"],
            "difficulty": difficulty,
            "hints": list(lab["hints"]),
            "verification_rubric": lab["verification_rubric"],
            "spawn_origin": "hacking_labs_seed_t5",
            "language": "en",
        }

        # question = "title\n\ntask" — mirrors the UX convention used by
        # the code-exercise seeder (title-like one-liner, blank line,
        # markdown body).
        question_text = f"{lab['title']}\n\n{lab['task']}"

        cur.execute(
            """
            INSERT INTO practice_problems (
                id, course_id, content_node_id, question_type, question,
                options, correct_answer, explanation, order_index,
                knowledge_points, source, difficulty_layer, problem_metadata,
                parent_problem_id, is_diagnostic, source_batch_id, source_version,
                is_archived, source_owner, locked, created_at
            ) VALUES (
                ?, ?, NULL, 'lab_exercise', ?,
                NULL, NULL, ?, ?,
                ?, 'curated', ?, ?,
                NULL, 0, NULL, 1,
                0, 'curated', 0, ?
            )
            """,
            (
                pid,
                course_id,
                question_text,
                lab["explanation"],
                next_order,
                json.dumps(lab["knowledge_points"]),
                DIFFICULTY_LAYER[difficulty],
                json.dumps(metadata),
                now,
            ),
        )
        inserted.append((pid, lab["title"]))
        print(f"  + {pid[:8]}... '{lab_id}' — {lab['title']}")

    conn.commit()
    conn.close()

    print(
        f"\nInserted {len(inserted)} lab_exercise card(s); "
        f"skipped {len(skipped)} already-seeded."
    )
    if inserted:
        print("IDs:")
        for pid, title in inserted:
            print(f"  {pid}  {title}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "usage: python seed_hacking_labs.py <course_id>",
            file=sys.stderr,
        )
        sys.exit(1)
    seed(sys.argv[1])
