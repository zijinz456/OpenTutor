"""Seed Python code-exercise practice problems (§34.5 Phase 11 T5).

Usage:
    docker cp scripts/seed_code_exercises.py opentutor-api:/tmp/seed.py
    docker exec opentutor-api python /tmp/seed.py <course_id>

Run inside the api container — needs sqlite3 access to /app/data/opentutor.db.
"""
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

CARDS = [
    {
        "question": "Print the numbers 1 through 5, one per line.",
        "starter_code": "# Print 1, 2, 3, 4, 5 — one per line\nfor i in range(...):\n    print(...)\n",
        "expected_output": "1\n2\n3\n4\n5",
        "stdout_normalizer": "rstrip",
        "hints": [
            "range(1, 6) gives you 1..5",
            "`print(i)` prints each on its own line"
        ],
        "knowledge_points": ["loops", "range", "print"],
        "explanation": "range(start, stop) is exclusive on the stop argument, so range(1, 6) yields 1..5."
    },
    {
        "question": "Given a list `nums = [3, 1, 4, 1, 5, 9, 2, 6]`, print the largest number.",
        "starter_code": "nums = [3, 1, 4, 1, 5, 9, 2, 6]\n# print the largest value\n",
        "expected_output": "9",
        "stdout_normalizer": "rstrip",
        "hints": [
            "Python has a builtin for this",
            "`max(nums)` gives the largest"
        ],
        "knowledge_points": ["builtins", "max", "lists"],
        "explanation": "max() on a list returns the largest element. print(max(nums)) → 9."
    },
    {
        "question": "Write a function `double(x)` that returns x * 2. Print double(7).",
        "starter_code": "def double(x):\n    # return double of x\n    pass\n\nprint(double(7))\n",
        "expected_output": "14",
        "stdout_normalizer": "rstrip",
        "hints": [
            "Replace `pass` with a return statement",
            "`return x * 2`"
        ],
        "knowledge_points": ["functions", "return"],
        "explanation": "A function body that only has `pass` returns None. Replace with `return x * 2` to actually compute."
    },
    {
        "question": "Count how many vowels (a, e, i, o, u) are in the word 'dopamine'. Print the count.",
        "starter_code": "word = \"dopamine\"\nvowels = \"aeiou\"\ncount = 0\n# loop through word and count vowels\n\nprint(count)\n",
        "expected_output": "4",
        "stdout_normalizer": "rstrip",
        "hints": [
            "Loop with `for ch in word:`",
            "Check `if ch in vowels:` and increment count"
        ],
        "knowledge_points": ["strings", "loops", "conditions"],
        "explanation": "Vowels in 'dopamine': o, a, i, e → 4 total. `for ch in word: if ch in vowels: count += 1`"
    },
    {
        "question": "Given `words = ['apple', 'banana', 'cherry']`, print each word UPPERCASE on its own line.",
        "starter_code": "words = ['apple', 'banana', 'cherry']\n# print each uppercased\n",
        "expected_output": "APPLE\nBANANA\nCHERRY",
        "stdout_normalizer": "rstrip",
        "hints": [
            "Loop: `for w in words:`",
            "`w.upper()` returns uppercased string"
        ],
        "knowledge_points": ["strings", "methods", "loops"],
        "explanation": "str.upper() returns an uppercase copy of the string. Iterate and print each."
    },
]


def seed(course_id: str, db_path: str = "/app/data/opentutor.db") -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Verify course exists
    course = cur.execute("SELECT name FROM courses WHERE id=?", (course_id,)).fetchone()
    if not course:
        print(f"ERROR: course {course_id} not found", file=sys.stderr)
        sys.exit(1)
    print(f"Seeding into course: {course[0]}")

    # Find max existing order_index so we append
    max_order = cur.execute(
        "SELECT COALESCE(MAX(order_index), 0) FROM practice_problems WHERE course_id=?",
        (course_id,),
    ).fetchone()[0]

    now = datetime.now(timezone.utc).isoformat()
    inserted: list[str] = []
    for i, card in enumerate(CARDS, start=1):
        pid = str(uuid.uuid4())
        metadata = {
            "starter_code": card["starter_code"],
            "expected_output": card["expected_output"],
            "stdout_normalizer": card["stdout_normalizer"],
            "hints": card["hints"],
            "spawn_origin": "code_runner_seed_t5",
            "language": "python",
        }
        cur.execute(
            """
            INSERT INTO practice_problems (
                id, course_id, content_node_id, question_type, question,
                options, correct_answer, explanation, order_index,
                knowledge_points, source, difficulty_layer, problem_metadata,
                parent_problem_id, is_diagnostic, source_batch_id, source_version,
                is_archived, source_owner, locked, created_at
            ) VALUES (
                ?, ?, NULL, 'code_exercise', ?,
                NULL, NULL, ?, ?,
                ?, 'ai_generated', 1, ?,
                NULL, 0, NULL, 1,
                0, 'ai', 0, ?
            )
            """,
            (
                pid, course_id, card["question"], card["explanation"],
                max_order + i,
                json.dumps(card["knowledge_points"]),
                json.dumps(metadata),
                now,
            ),
        )
        inserted.append(pid)
        print(f"  + {pid[:8]}... '{card['question'][:50]}...'")

    conn.commit()
    conn.close()
    print(f"\nInserted {len(inserted)} code_exercise cards. IDs:")
    for pid in inserted:
        print(f"  {pid}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python seed_code_exercises.py <course_id>", file=sys.stderr)
        sys.exit(1)
    seed(sys.argv[1])
