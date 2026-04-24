# ruff: noqa: E501
"""Transpile a book chapter into a compiled drill course YAML (Phase 16c T5b).

Reads a source PDF (offline-corpus, trusted content committed to the repo),
extracts a chapter's text, asks the provider chain (Groq primary, OpenAI
fallback) to emit a batch of drills in the exact schema
:mod:`services.drill_loader` consumes, gates each candidate through the
:mod:`services.drill_runner` sandbox (reference_solution MUST pass
hidden_tests), and writes the survivors out as
``content/drills/{slug}/{version}/course.yaml``.

**Threat model.** Source material is the trusted offline corpus
(``offline_corpus/...``) committed to this repo. We do NOT accept
user-supplied PDFs here — the ``--source`` flag is author-controlled,
not exposed over HTTP. Generated drills are still executed in the
sandboxed runner at the reference-solution gate, so a compromised LLM
output can't exec code outside the subprocess isolation the runner
already provides.

**Cost ballpark.** Groq ``llama-3.3-70b-versatile`` ≈ $0.59 / 1M input
tokens + $0.79 / 1M output tokens. A chapter of PY4E (~10k input + 4k
output tokens for 10 drills) ≈ $0.02 per chapter. Full book (15
chapters) ≈ $0.30 total — an afternoon of manual authoring saves this
cost many times over.

Usage::

    python scripts/transpile_drills.py \\
      --source offline_corpus/python/py4e/pythonlearn.pdf \\
      --course-slug py4e \\
      --course-title "Python for Everybody" \\
      --source-label py4e \\
      --version v1.0.0 \\
      --chapter 1 \\
      --drills-per-chapter 10 \\
      --output content/drills/py4e/v1.0.0/course.yaml \\
      [--dry-run]

``--dry-run`` skips the LLM call and emits deterministic fixture drills
(useful in CI / when provider keys are unset).
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# apps/api is the import root outside the container (mirrors
# scripts.seed_python_paths pattern).
_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from config import settings  # noqa: E402
from services.drill_runner import run_drill  # noqa: E402


# ── PDF chapter extraction ──────────────────────────────────────────


# Hardcoded PY4E chapter page ranges (inclusive, 0-indexed). Derived from
# chapter heading detection in the committed PDF and kept explicit so the
# content source remains auditable.
PY4E_CHAPTER_PAGES: dict[int, tuple[int, int]] = {
    1: (12, 29),  # Why should you learn to write programs?
    2: (30, 41),  # Variables, expressions, and statements
    3: (42, 53),  # Conditional execution
    4: (54, 67),  # Functions
    5: (68, 77),  # Iteration
    6: (78, 89),  # Strings
    7: (90, 101),  # Files
    8: (102, 119),  # Lists
    9: (120, 129),  # Dictionaries
    10: (130, 141),  # Tuples
    11: (142, 155),  # Regular expressions
    12: (156, 169),  # Networked programs
    13: (170, 177),  # Using Web Services
    14: (178, 191),  # Object-oriented programming
    15: (192, 215),  # Using Databases and SQL
    16: (216, 227),  # Visualizing data
}

PY4E_CHAPTER_TITLES: dict[int, str] = {
    1: "Why Should You Learn to Write Programs?",
    2: "Variables, Expressions, and Statements",
    3: "Conditional Execution",
    4: "Functions",
    5: "Iteration",
    6: "Strings",
    7: "Files",
    8: "Lists",
    9: "Dictionaries",
    10: "Tuples",
    11: "Regular Expressions",
    12: "Networked Programs",
    13: "Using Web Services",
    14: "Object-Oriented Programming",
    15: "Using Databases and SQL",
    16: "Visualizing Data",
}

CS50P_WEEK_FILES: dict[int, str] = {
    0: "week_0.html",
    1: "week_1.html",
    2: "week_2.html",
}

CS50P_WEEK_TITLES: dict[int, str] = {
    0: "Functions, Variables",
    1: "Conditionals",
    2: "Loops",
}

COURSE_SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "py4e": {
        "source_kind": "pdf",
        "unit_paths": PY4E_CHAPTER_PAGES,
        "unit_titles": PY4E_CHAPTER_TITLES,
        "module_slug_prefix": "ch",
        "module_label": "Chapter",
        "citation_example": "PY4E §1.2 Example 1.1",
        "description": (
            "Short, checked Python drills compiled from the PY4E book. "
            "Each drill focuses on one small idea and keeps the theory on demand."
        ),
        "estimated_hours": 12,
    },
    "cs50p": {
        "source_kind": "html",
        "unit_paths": CS50P_WEEK_FILES,
        "unit_titles": CS50P_WEEK_TITLES,
        "module_slug_prefix": "wk",
        "module_label": "Week",
        "citation_example": "CS50P Week 1 notes section 'compare.py'",
        "description": (
            "Short, checked Python drills compiled from CS50P lecture notes. "
            "Each drill turns one lecture idea into a tight practice loop."
        ),
        "estimated_hours": 8,
    },
}


def _get_course_source_spec(course_slug: str) -> dict[str, Any]:
    """Return the course-source spec for ``course_slug`` or fail clearly."""

    spec = COURSE_SOURCE_SPECS.get(course_slug)
    if spec is None:
        raise ValueError(
            f"unsupported course slug {course_slug!r}; "
            f"known courses: {sorted(COURSE_SOURCE_SPECS)!r}"
        )
    return spec


def extract_chapter_text(pdf_path: Path, chapter: int) -> str:
    """Return the plain-text content of ``chapter`` from ``pdf_path``.

    Uses a hardcoded page range (see :data:`PY4E_CHAPTER_PAGES`) rather
    than regex-scanning each page for "Chapter N" headers — the headers
    are clean in the PY4E PDF but future book sources may not be, and
    hardcoded ranges are trivially auditable.
    """

    import pypdf  # local import — pypdf is a dev-only dep, not in pyproject

    if chapter not in PY4E_CHAPTER_PAGES:
        raise ValueError(
            f"no page range registered for chapter {chapter}; "
            f"extend PY4E_CHAPTER_PAGES in {Path(__file__).name}"
        )

    start, end = PY4E_CHAPTER_PAGES[chapter]
    reader = pypdf.PdfReader(str(pdf_path))
    pages = reader.pages[start : end + 1]
    chunks: list[str] = []
    for page in pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks)


def _extract_main_html_text(html_path: Path) -> str:
    """Extract human-readable text from a CS50P week HTML page.

    The offline CS50P corpus is committed as full HTML pages with nav,
    headers, scripts, and resource links. We prefer the ``<main>``
    content when present, then collapse the fragment into plain text
    while preserving block boundaries as newlines.
    """

    raw = html_path.read_text(encoding="utf-8")
    match = re.search(
        r"<main\b[^>]*>(.*?)</main>",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    fragment = match.group(1) if match else raw
    fragment = re.sub(
        r"<(script|style)\b.*?</\1>",
        "",
        fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for tag in (
        "</p>",
        "</li>",
        "</ul>",
        "</ol>",
        "</pre>",
        "</code>",
        "</h1>",
        "</h2>",
        "</h3>",
        "</h4>",
        "</h5>",
        "</h6>",
        "<br>",
        "<br/>",
        "<br />",
    ):
        fragment = fragment.replace(tag, f"{tag}\n")
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_source_unit_text(source_path: Path, course_slug: str, chapter: int) -> str:
    """Return plain-text source material for one unit of a supported course."""

    spec = _get_course_source_spec(course_slug)
    unit_paths = spec["unit_paths"]
    if chapter not in unit_paths:
        raise ValueError(
            f"no source unit registered for {course_slug!r} chapter {chapter}; "
            f"extend the course metadata in {Path(__file__).name}"
        )

    source_kind = spec["source_kind"]
    if source_kind == "pdf":
        if not source_path.is_file():
            raise FileNotFoundError(f"PDF source not found: {source_path}")
        return extract_chapter_text(source_path, chapter)

    if source_kind == "html":
        html_path = source_path / unit_paths[chapter]
        if source_path.is_file():
            html_path = source_path
        if not html_path.is_file():
            raise FileNotFoundError(f"HTML source not found: {html_path}")
        return _extract_main_html_text(html_path)

    raise ValueError(f"unsupported source kind: {source_kind!r}")


# ── Drill-schema contract (mirrors services.drill_loader) ───────────


_REQUIRED_DRILL_KEYS = frozenset(
    {
        "slug",
        "title",
        "why_it_matters",
        "starter_code",
        "hidden_tests",
        "reference_solution",
        "hints",
        "skill_tags",
        "source_citation",
        "time_budget_min",
        "difficulty_layer",
    }
)


def validate_drill_shape(drill: dict[str, Any]) -> list[str]:
    """Return a list of human-readable shape errors; empty = valid.

    Kept in-module (not imported from ``drill_loader``) because importing
    that module pulls in sqlalchemy+models which the script doesn't
    need — but the key set MUST stay in sync. The loader re-validates
    at seed time, so any drift here will fail loudly on load.
    """

    errors: list[str] = []
    missing = _REQUIRED_DRILL_KEYS - set(drill.keys())
    if missing:
        errors.append(f"missing keys: {sorted(missing)!r}")
        return errors

    if not isinstance(drill["slug"], str) or not drill["slug"]:
        errors.append("slug must be a non-empty string")
    if not isinstance(drill["title"], str) or not drill["title"]:
        errors.append("title must be a non-empty string")
    if not isinstance(drill["why_it_matters"], str):
        errors.append("why_it_matters must be a string")
    elif len(drill["why_it_matters"]) > 500:
        errors.append(
            f"why_it_matters exceeds 500 chars ({len(drill['why_it_matters'])})"
        )
    if not isinstance(drill["starter_code"], str):
        errors.append("starter_code must be a string")
    if (
        not isinstance(drill["hidden_tests"], str)
        or "def test_" not in drill["hidden_tests"]
    ):
        errors.append("hidden_tests must be a pytest source string with a test_")
    if not isinstance(drill["reference_solution"], str):
        errors.append("reference_solution must be a string")
    if not isinstance(drill["hints"], list) or not all(
        isinstance(h, str) for h in drill["hints"]
    ):
        errors.append("hints must be a list[str]")
    if not isinstance(drill["skill_tags"], list) or not all(
        isinstance(t, str) for t in drill["skill_tags"]
    ):
        errors.append("skill_tags must be a list[str]")
    if not isinstance(drill["source_citation"], str) or not drill["source_citation"]:
        errors.append("source_citation must be a non-empty string")
    if not isinstance(drill["time_budget_min"], int):
        errors.append("time_budget_min must be int")
    elif drill["time_budget_min"] < 1 or drill["time_budget_min"] > 15:
        errors.append("time_budget_min out of sensible range [1, 15]")
    layer = drill["difficulty_layer"]
    if not isinstance(layer, int) or layer not in (1, 2, 3):
        errors.append("difficulty_layer must be 1/2/3")
    return errors


# ── Groq prompt + call ──────────────────────────────────────────────


_SYSTEM_PROMPT_TEMPLATE = """You are compiling practice drills from one unit of a programming course.
Output MUST be a single JSON object with key "drills" whose value is a
JSON array. Do not wrap in prose. Do not include markdown fences. Each
drill MUST obey this schema exactly:

{
  "slug": "kebab-case-unique-within-__UNIT_SCOPE__",
  "title": "Short imperative title (e.g. 'Convert inches to centimeters')",
  "why_it_matters": "<=500 chars: one sentence explaining the concept being practiced",
  "starter_code": "Python skeleton with explicit TODO and clear function signature",
  "hidden_tests": "Full pytest file content. MUST include `from solution import ...` and at least 2 `def test_*` functions covering happy path and one edge case.",
  "reference_solution": "Complete working solution that, when saved as solution.py, makes hidden_tests pass.",
  "hints": ["cheapest hint", "middle hint", "most-revealing hint"],
  "skill_tags": ["variables", "arithmetic"],
  "source_citation": "__CITATION_EXAMPLE__ (or similar precise pointer)",
  "time_budget_min": 5,
  "difficulty_layer": 1
}

ADHD-safe constraints:
- Each drill doable in <=10 minutes (time_budget_min between 2 and 10).
- Single learning objective per drill; no prerequisite chaining within the batch.
- starter_code shows the skeleton and leaves the CORE logic as a visible TODO.
- hints ordered cheapest-to-most-revealing; 3 hints is standard.
- difficulty_layer: 1=recall/fill-blank, 2=apply concept to new input, 3=combine two concepts.

Quality gates (your output will be rejected if these fail):
- reference_solution MUST pass hidden_tests when written as solution.py and run under pytest.
- source_citation MUST reference a specific part of the source material for this __UNIT_SCOPE__.
- Do NOT invent pedagogy the source material doesn't teach. Faithfully transcribe/adapt exercises the course presents.
- hidden_tests MUST be hermetic: use only literals, pytest fixtures such as tmp_path/monkeypatch/capsys, or data created inside the test file.
- Never require external files, live network calls, databases, cwd-dependent paths, or resources outside the generated pytest file.
- For file/network/database topics, prefer pure helper functions that receive text/records/URLs to parse, or create the temp fixture inside hidden_tests.
- hidden_tests should import explicit symbols (for example `from solution import count_words`) instead of `from solution import *`.
- Reference solutions must define only the requested functions/classes; do not run demo code, instantiate objects, or print at module import time unless the drill explicitly tests stdout from a function call.
- File drills must use the path object or filename passed in by the test. Do not hardcode filenames like `mbox.txt`.
- Network drills must mock `urllib`/socket behavior in tests or operate on already-fetched text/HTML/XML/JSON passed into the function.
- Database drills must use `sqlite3.connect(':memory:')` or a tmp_path database created in the test, never a real on-disk app database.
- OOP drills should test class behavior via method calls on instances created inside the test, not side effects at import time.
"""


def build_system_prompt(unit_scope: str, citation_example: str) -> str:
    """Render the generic system prompt for one course unit kind."""

    return _SYSTEM_PROMPT_TEMPLATE.replace(
        "__UNIT_SCOPE__", unit_scope.lower()
    ).replace("__CITATION_EXAMPLE__", citation_example)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first ``{...}`` JSON object out of ``text``.

    Groq's JSON mode returns clean JSON, but we fall back to a regex
    extract in case the model streams a stray header line. Using
    ``json.loads`` on the first balanced-brace substring is good enough
    for a trusted-author pipeline.
    """

    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object found in LLM response: {text[:200]!r}")
    return json.loads(match.group(0))


_GROQ_MODEL = "llama-3.3-70b-versatile"
_OPENAI_FALLBACK_MODEL = "gpt-4o-mini"


def _available_provider_specs() -> list[dict[str, str]]:
    """Return provider specs in priority order: Groq first, OpenAI second."""

    groq_key = os.environ.get("GROQ_API_KEY") or settings.groq_api_key
    openai_key = os.environ.get("OPENAI_API_KEY") or settings.openai_api_key
    providers: list[dict[str, str]] = []
    if groq_key:
        providers.append(
            {
                "provider": "groq",
                "api_key": groq_key,
                "base_url": "https://api.groq.com/openai/v1",
                "model": _GROQ_MODEL,
            }
        )
    if openai_key:
        providers.append(
            {
                "provider": "openai",
                "api_key": openai_key,
                "model": _OPENAI_FALLBACK_MODEL,
            }
        )
    return providers


def _call_provider(
    provider_spec: dict[str, str],
    system_prompt: str,
    user_prompt: str,
) -> list[dict[str, Any]]:
    """Ask one provider for drills from one course unit; return them."""

    from openai import OpenAI

    base_url = provider_spec.get("base_url")
    if base_url:
        client = OpenAI(api_key=provider_spec["api_key"], base_url=base_url)
    else:
        client = OpenAI(api_key=provider_spec["api_key"])

    resp = client.chat.completions.create(
        model=provider_spec["model"],
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = resp.choices[0].message.content or ""
    doc = _extract_json_object(raw)
    drills = doc.get("drills")
    if not isinstance(drills, list):
        raise ValueError(
            f"{provider_spec['provider']} response missing 'drills' list: keys={list(doc)!r}"
        )
    return drills


def call_llm(
    course_title: str,
    unit_label: str,
    unit_number: int,
    unit_title: str,
    unit_text: str,
    n_drills: int,
    citation_example: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Try Groq first, then OpenAI; return provider name plus drill list."""

    system_prompt = build_system_prompt(
        unit_scope=unit_label,
        citation_example=citation_example,
    )
    user_prompt = (
        f"Course: {course_title}\n"
        f"Unit: {unit_label} {unit_number}: {unit_title}\n"
        f"Generate exactly {n_drills} drills based on the source text below.\n"
        "Each drill must cite the specific section, example, exercise, or "
        "named code sample it derives from.\n\n"
        f"=== SOURCE TEXT ===\n{unit_text}\n=== END ==="
    )

    errors: list[str] = []
    for provider_spec in _available_provider_specs():
        try:
            drills = _call_provider(
                provider_spec=provider_spec,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            return provider_spec["provider"], drills
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{provider_spec['provider']}: {exc}")

    if not errors:
        raise RuntimeError(
            "no LLM provider configured; set GROQ_API_KEY or OPENAI_API_KEY, "
            "or use --dry-run for deterministic fixtures"
        )
    raise RuntimeError(f"all LLM providers failed: {' | '.join(errors)}")


# ── Reference-solution gate (the critical one) ──────────────────────


async def gate_drill(drill: dict[str, Any]) -> tuple[bool, str]:
    """Run ``reference_solution`` against ``hidden_tests``; return (passed, output).

    This is the single most important quality gate — a drill whose
    reference solution fails its own tests is an unsolvable puzzle for
    the learner, and reviewing 10 such drills manually wastes the day-4
    T19 window. We keep the runner timeout tight (10s) because a
    reference solution ought to be crisp; anything slower is a sign
    the model dumped a pathological loop.
    """

    result = await run_drill(
        drill["reference_solution"],
        drill["hidden_tests"],
        timeout_s=10.0,
    )
    return result.passed, result.output


# ── Fallback fixture (when GROQ_API_KEY unset or --dry-run) ─────────


def _fixture_drills_chapter1() -> list[dict[str, Any]]:
    """Hand-transcribed drills for PY4E Chapter 1 §1.1–1.5.

    Used when ``GROQ_API_KEY`` is unset OR ``--dry-run`` is passed, so
    the pipeline still produces a reviewable YAML. Every drill cites a
    specific PY4E section — we're not inventing pedagogy, we're wrapping
    one of Severance's own examples with a single clear test.
    """

    return [
        {
            "slug": "print-hello-world",
            "title": "Print Hello, World",
            "why_it_matters": "Running your first program establishes the edit-run loop every Python exercise depends on.",
            "starter_code": 'def greet() -> str:\n    """Return the string: Hello, World!"""\n    # TODO: return the greeting string\n    ...\n',
            "hidden_tests": "from solution import greet\n\ndef test_returns_hello_world():\n    assert greet() == 'Hello, World!'\n\ndef test_returns_string():\n    assert isinstance(greet(), str)\n",
            "reference_solution": "def greet() -> str:\n    return 'Hello, World!'\n",
            "hints": [
                "A function 'returns' a value with the return keyword.",
                "The expected string must match exactly, including the comma and exclamation mark.",
                "return 'Hello, World!'",
            ],
            "skill_tags": ["functions", "strings", "basics"],
            "source_citation": "PY4E Ch1 §1.1 'Creativity and motivation' (classic print('Hello, World!') opener).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "sum-two-numbers",
            "title": "Add two numbers",
            "why_it_matters": "Arithmetic on inputs is the minimum unit of 'computation' — covered in PY4E Ch1 as the core of what programs do.",
            "starter_code": "def add(a: int, b: int) -> int:\n    # TODO: return the sum of a and b\n    ...\n",
            "hidden_tests": "from solution import add\n\ndef test_positive():\n    assert add(2, 3) == 5\n\ndef test_zero():\n    assert add(0, 0) == 0\n\ndef test_negative():\n    assert add(-4, 10) == 6\n",
            "reference_solution": "def add(a: int, b: int) -> int:\n    return a + b\n",
            "hints": [
                "Use the + operator.",
                "Return the result directly; no print().",
                "return a + b",
            ],
            "skill_tags": ["arithmetic", "functions"],
            "source_citation": "PY4E Ch1 §1.4 'Terminology: interpreter and compiler' (arithmetic as the foundational program).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "square-a-number",
            "title": "Square a number",
            "why_it_matters": "Exponentiation introduces Python's ** operator, the first non-trivial arithmetic symbol PY4E covers after +, -, *, /.",
            "starter_code": "def square(x: float) -> float:\n    # TODO: return x raised to the power 2\n    ...\n",
            "hidden_tests": "from solution import square\n\ndef test_integer():\n    assert square(5) == 25\n\ndef test_zero():\n    assert square(0) == 0\n\ndef test_float():\n    assert abs(square(1.5) - 2.25) < 1e-9\n",
            "reference_solution": "def square(x: float) -> float:\n    return x ** 2\n",
            "hints": [
                "Python's exponent operator is ** (two stars).",
                "x*x also works but the drill asks you to use the power operator.",
                "return x ** 2",
            ],
            "skill_tags": ["arithmetic", "exponent"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (arithmetic building blocks).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "concat-strings",
            "title": "Concatenate two strings with a space",
            "why_it_matters": "String concatenation is one of Ch1's first named data operations and the basis of later text-processing drills.",
            "starter_code": 'def greet(name: str) -> str:\n    """Return the string "Hello, <name>!"."""\n    # TODO: build the greeting using + or an f-string\n    ...\n',
            "hidden_tests": "from solution import greet\n\ndef test_basic():\n    assert greet('Ada') == 'Hello, Ada!'\n\ndef test_empty():\n    assert greet('') == 'Hello, !'\n",
            "reference_solution": "def greet(name: str) -> str:\n    return 'Hello, ' + name + '!'\n",
            "hints": [
                "String + string = concatenation.",
                "Include the comma and space inside the literal.",
                "return 'Hello, ' + name + '!'",
            ],
            "skill_tags": ["strings", "concatenation"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (string operations introduced alongside arithmetic).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "integer-division",
            "title": "Integer division vs true division",
            "why_it_matters": "Ch1 distinguishes Python's / (true division) from // (floor division) — a classic beginner confusion worth nailing early.",
            "starter_code": "def divide_floor(a: int, b: int) -> int:\n    # TODO: return the integer quotient (floor division) of a by b\n    ...\n",
            "hidden_tests": "from solution import divide_floor\n\ndef test_exact():\n    assert divide_floor(10, 2) == 5\n\ndef test_truncates():\n    assert divide_floor(7, 2) == 3\n\ndef test_larger_divisor():\n    assert divide_floor(3, 10) == 0\n",
            "reference_solution": "def divide_floor(a: int, b: int) -> int:\n    return a // b\n",
            "hints": [
                "Python has two division operators: / and //.",
                "// truncates toward negative infinity and returns an int when both operands are ints.",
                "return a // b",
            ],
            "skill_tags": ["arithmetic", "integer-division"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (Python's operator set).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "modulo-remainder",
            "title": "Compute a remainder with %",
            "why_it_matters": "The modulo operator is introduced alongside division in Ch1 and powers even/odd checks, cycling, and hashing later.",
            "starter_code": "def remainder(a: int, b: int) -> int:\n    # TODO: return the remainder of a divided by b\n    ...\n",
            "hidden_tests": "from solution import remainder\n\ndef test_simple():\n    assert remainder(10, 3) == 1\n\ndef test_even():\n    assert remainder(8, 2) == 0\n\ndef test_larger_b():\n    assert remainder(3, 10) == 3\n",
            "reference_solution": "def remainder(a: int, b: int) -> int:\n    return a % b\n",
            "hints": [
                "Python's remainder operator is % (percent sign).",
                "10 % 3 is 1 because 10 = 3*3 + 1.",
                "return a % b",
            ],
            "skill_tags": ["arithmetic", "modulo"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (operator introductions).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "assign-and-return",
            "title": "Assign a value to a variable and return it",
            "why_it_matters": "The assignment statement is Ch2's subject but is first shown in Ch1's worked example — this drill nails the x = value pattern.",
            "starter_code": "def pi_approx() -> float:\n    # TODO: assign 3.14159 to a variable, then return it\n    ...\n",
            "hidden_tests": "from solution import pi_approx\n\ndef test_value():\n    assert abs(pi_approx() - 3.14159) < 1e-9\n\ndef test_type():\n    assert isinstance(pi_approx(), float)\n",
            "reference_solution": "def pi_approx() -> float:\n    pi = 3.14159\n    return pi\n",
            "hints": [
                "Use the = operator to bind a name to a value.",
                "Then return that name.",
                "pi = 3.14159; return pi",
            ],
            "skill_tags": ["variables", "assignment"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (first worked example uses assignment).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "convert-inches-to-cm",
            "title": "Convert inches to centimeters",
            "why_it_matters": "Unit conversion is the prototypical 'plug a constant into a formula' exercise Ch1 uses to show what programs do.",
            "starter_code": "def inches_to_cm(inches: float) -> float:\n    # TODO: return inches * 2.54\n    ...\n",
            "hidden_tests": "from solution import inches_to_cm\n\ndef test_zero():\n    assert inches_to_cm(0) == 0\n\ndef test_one_inch():\n    assert abs(inches_to_cm(1) - 2.54) < 1e-9\n\ndef test_foot():\n    assert abs(inches_to_cm(12) - 30.48) < 1e-9\n",
            "reference_solution": "def inches_to_cm(inches: float) -> float:\n    return inches * 2.54\n",
            "hints": [
                "One inch is 2.54 centimeters.",
                "Multiply the input by the conversion factor.",
                "return inches * 2.54",
            ],
            "skill_tags": ["arithmetic", "functions"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (worked arithmetic examples).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "average-of-two",
            "title": "Average of two numbers",
            "why_it_matters": "Combining arithmetic ops into an expression is Ch1's first multi-operator example — operator precedence matters here.",
            "starter_code": "def average(a: float, b: float) -> float:\n    # TODO: return the arithmetic mean of a and b\n    ...\n",
            "hidden_tests": "from solution import average\n\ndef test_both_positive():\n    assert abs(average(4, 6) - 5.0) < 1e-9\n\ndef test_with_zero():\n    assert abs(average(0, 10) - 5.0) < 1e-9\n\ndef test_negative():\n    assert abs(average(-4, 4) - 0.0) < 1e-9\n",
            "reference_solution": "def average(a: float, b: float) -> float:\n    return (a + b) / 2\n",
            "hints": [
                "Add the two numbers, then divide by 2.",
                "Parentheses matter: (a + b) / 2, not a + b / 2.",
                "return (a + b) / 2",
            ],
            "skill_tags": ["arithmetic", "precedence"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (combining operators).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "print-vs-return",
            "title": "Return rather than print",
            "why_it_matters": "Ch1 introduces print as output; this drill contrasts it with return, which the rest of PY4E relies on for testable functions.",
            "starter_code": "def double(x: int) -> int:\n    # TODO: return 2*x. Do NOT use print().\n    ...\n",
            "hidden_tests": "from solution import double\n\ndef test_returns_value():\n    assert double(3) == 6\n\ndef test_does_not_print(capsys):\n    double(5)\n    captured = capsys.readouterr()\n    assert captured.out == ''\n",
            "reference_solution": "def double(x: int) -> int:\n    return 2 * x\n",
            "hints": [
                "print() sends text to stdout; return hands a value back to the caller.",
                "A function with no return yields None.",
                "return 2 * x",
            ],
            "skill_tags": ["functions", "return"],
            "source_citation": "PY4E Ch1 §1.5 'Writing a program' (contrast between output and values).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
    ]


def _fixture_drills_chapter2() -> list[dict[str, Any]]:
    """Hand-transcribed drills for PY4E Chapter 2 §2.1–2.10."""

    return [
        {
            "slug": "return-an-integer",
            "title": "Return an integer value",
            "why_it_matters": (
                "Chapter 2 starts by separating values from their types. "
                "Returning a plain integer is the smallest possible typed value."
            ),
            "starter_code": (
                "def lucky_number() -> int:\n"
                "    # TODO: return the integer 17\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import lucky_number\n\n"
                "def test_value():\n"
                "    assert lucky_number() == 17\n\n"
                "def test_type():\n"
                "    assert isinstance(lucky_number(), int)\n"
            ),
            "reference_solution": ("def lucky_number() -> int:\n    return 17\n"),
            "hints": [
                "Integers have no quotes and no decimal point.",
                "Return the value directly.",
                "return 17",
            ],
            "skill_tags": ["values", "types", "integers"],
            "source_citation": "PY4E Ch2 §2.1 'Values and types' (integers vs strings).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "return-a-float",
            "title": "Return a float value",
            "why_it_matters": (
                "Chapter 2 introduces floating-point numbers as a distinct type. "
                "Seeing the decimal point matters early."
            ),
            "starter_code": (
                "def pi_starter() -> float:\n"
                "    # TODO: return the float 3.2\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import pi_starter\n\n"
                "def test_value():\n"
                "    assert abs(pi_starter() - 3.2) < 1e-9\n\n"
                "def test_type():\n"
                "    assert isinstance(pi_starter(), float)\n"
            ),
            "reference_solution": ("def pi_starter() -> float:\n    return 3.2\n"),
            "hints": [
                "Floats use a decimal point.",
                "Do not wrap the number in quotes.",
                "return 3.2",
            ],
            "skill_tags": ["values", "types", "floats"],
            "source_citation": "PY4E Ch2 §2.1 'Values and types' (float examples).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "assign-message-variable",
            "title": "Assign to a variable before returning",
            "why_it_matters": (
                "Variables are names that refer to values. "
                "This drill makes the assignment statement visible."
            ),
            "starter_code": (
                "def make_message() -> str:\n"
                "    # TODO: store 'And now for something completely different' "
                "in a variable named message and return it\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import make_message\n\n"
                "def test_value():\n"
                "    assert make_message() == 'And now for something completely different'\n\n"
                "def test_type():\n"
                "    assert isinstance(make_message(), str)\n"
            ),
            "reference_solution": (
                "def make_message() -> str:\n"
                "    message = 'And now for something completely different'\n"
                "    return message\n"
            ),
            "hints": [
                "Use = to bind the name message to a string.",
                "Return the variable after assigning it.",
                "message = 'And now for something completely different'; return message",
            ],
            "skill_tags": ["variables", "assignment", "strings"],
            "source_citation": "PY4E Ch2 §2.2 'Variables' (message = ... example).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "seconds-since-midnight",
            "title": "Compute seconds since midnight",
            "why_it_matters": (
                "The book uses variables plus arithmetic to show how expressions "
                "turn a little data into something useful."
            ),
            "starter_code": (
                "def seconds_since_midnight(hour: int, minute: int) -> int:\n"
                "    # TODO: return the total seconds represented by hour and minute\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import seconds_since_midnight\n\n"
                "def test_whole_hour():\n"
                "    assert seconds_since_midnight(1, 0) == 3600\n\n"
                "def test_hour_and_minute():\n"
                "    assert seconds_since_midnight(2, 30) == 9000\n\n"
                "def test_midnight():\n"
                "    assert seconds_since_midnight(0, 0) == 0\n"
            ),
            "reference_solution": (
                "def seconds_since_midnight(hour: int, minute: int) -> int:\n"
                "    return hour * 3600 + minute * 60\n"
            ),
            "hints": [
                "There are 3600 seconds in an hour and 60 seconds in a minute.",
                "Multiply first, then add the two parts together.",
                "return hour * 3600 + minute * 60",
            ],
            "skill_tags": ["variables", "operators", "arithmetic"],
            "source_citation": "PY4E Ch2 §2.5 'Operators and operands' (hour/minute examples).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "floor-divide-minutes",
            "title": "Use floor division for whole hours",
            "why_it_matters": (
                "Chapter 2 explicitly contrasts true division and floor division. "
                "This drill makes the difference concrete."
            ),
            "starter_code": (
                "def whole_hours(total_minutes: int) -> int:\n"
                "    # TODO: return the number of full hours in total_minutes\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import whole_hours\n\n"
                "def test_exact_hour():\n"
                "    assert whole_hours(120) == 2\n\n"
                "def test_partial_hour():\n"
                "    assert whole_hours(59) == 0\n\n"
                "def test_more_than_two():\n"
                "    assert whole_hours(185) == 3\n"
            ),
            "reference_solution": (
                "def whole_hours(total_minutes: int) -> int:\n"
                "    return total_minutes // 60\n"
            ),
            "hints": [
                "Use //, not /, when you want the whole-number quotient.",
                "59 // 60 is 0.",
                "return total_minutes // 60",
            ],
            "skill_tags": ["operators", "division", "floor-division"],
            "source_citation": "PY4E Ch2 §2.5 'Operators and operands' (minute / 60 example).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "modulo-last-digit",
            "title": "Get the last digit with modulo",
            "why_it_matters": (
                "The modulus operator is introduced as a practical way to "
                "extract remainders and right-most digits."
            ),
            "starter_code": (
                "def last_digit(number: int) -> int:\n"
                "    # TODO: return the right-most digit of number\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import last_digit\n\n"
                "def test_simple():\n"
                "    assert last_digit(47) == 7\n\n"
                "def test_zero():\n"
                "    assert last_digit(120) == 0\n\n"
                "def test_single_digit():\n"
                "    assert last_digit(5) == 5\n"
            ),
            "reference_solution": (
                "def last_digit(number: int) -> int:\n    return number % 10\n"
            ),
            "hints": [
                "The remainder after dividing by 10 is the last digit.",
                "Use the % operator.",
                "return number % 10",
            ],
            "skill_tags": ["operators", "modulo", "digits"],
            "source_citation": "PY4E Ch2 §2.8 'Modulus operator' (right-most digit example).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "join-name-parts",
            "title": "Join two strings end to end",
            "why_it_matters": (
                "String concatenation is one of the first non-math operations "
                "on values in Chapter 2."
            ),
            "starter_code": (
                "def full_name(first: str, last: str) -> str:\n"
                "    # TODO: return first + ' ' + last\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import full_name\n\n"
                "def test_basic():\n"
                "    assert full_name('Ada', 'Lovelace') == 'Ada Lovelace'\n\n"
                "def test_empty_last():\n"
                "    assert full_name('Ada', '') == 'Ada '\n"
            ),
            "reference_solution": (
                "def full_name(first: str, last: str) -> str:\n"
                "    return first + ' ' + last\n"
            ),
            "hints": [
                "Use + for string concatenation.",
                "The space belongs in the middle as its own string.",
                "return first + ' ' + last",
            ],
            "skill_tags": ["strings", "concatenation"],
            "source_citation": "PY4E Ch2 §2.9 'String operations' (+ joins strings).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "repeat-string",
            "title": "Repeat a string with *",
            "why_it_matters": (
                "Chapter 2 shows that * works on strings too. "
                "This is a memorable early example of Python overloading operators."
            ),
            "starter_code": (
                "def echo_word(word: str, times: int) -> str:\n"
                "    # TODO: return word repeated times times\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import echo_word\n\n"
                "def test_three_times():\n"
                "    assert echo_word('Hi', 3) == 'HiHiHi'\n\n"
                "def test_zero_times():\n"
                "    assert echo_word('Hi', 0) == ''\n"
            ),
            "reference_solution": (
                "def echo_word(word: str, times: int) -> str:\n"
                "    return word * times\n"
            ),
            "hints": [
                "The * operator can repeat a string by an integer count.",
                "Do not add spaces unless the tests ask for them.",
                "return word * times",
            ],
            "skill_tags": ["strings", "operators", "repetition"],
            "source_citation": "PY4E Ch2 §2.9 'String operations' (* repeats strings).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "parse-integer-input",
            "title": "Convert text input to an integer",
            "why_it_matters": (
                "The book warns that input returns strings. "
                "Turning text digits into numbers is the bridge to real calculations."
            ),
            "starter_code": (
                "def parse_count(raw: str) -> int:\n"
                "    # TODO: convert raw to an integer and return it\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import parse_count\n\n"
                "def test_plain_digits():\n"
                "    assert parse_count('17') == 17\n\n"
                "def test_zero():\n"
                "    assert parse_count('0') == 0\n"
            ),
            "reference_solution": (
                "def parse_count(raw: str) -> int:\n    return int(raw)\n"
            ),
            "hints": [
                "input() gives you a string, even when the user typed digits.",
                "Use the int() conversion function.",
                "return int(raw)",
            ],
            "skill_tags": ["input", "conversion", "integers"],
            "source_citation": "PY4E Ch2 §2.10 'Asking the user for input' (int(speed)).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "fahrenheit-to-celsius",
            "title": "Convert Fahrenheit to Celsius",
            "why_it_matters": (
                "The Fahrenheit example shows how user input, float conversion, "
                "and arithmetic combine into a useful tiny program."
            ),
            "starter_code": (
                "def fahrenheit_to_celsius(raw_fahr: str) -> float:\n"
                "    # TODO: parse raw_fahr as a float and convert it to Celsius\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import fahrenheit_to_celsius\n\n"
                "def test_freezing_point():\n"
                "    assert abs(fahrenheit_to_celsius('32') - 0.0) < 1e-9\n\n"
                "def test_boiling_point():\n"
                "    assert abs(fahrenheit_to_celsius('212') - 100.0) < 1e-9\n\n"
                "def test_body_temp():\n"
                "    assert abs(fahrenheit_to_celsius('98.6') - 37.0) < 1e-9\n"
            ),
            "reference_solution": (
                "def fahrenheit_to_celsius(raw_fahr: str) -> float:\n"
                "    fahr = float(raw_fahr)\n"
                "    return (fahr - 32.0) * 5.0 / 9.0\n"
            ),
            "hints": [
                "Convert the raw text with float() before doing arithmetic.",
                "Use the book's formula: (fahr - 32.0) * 5.0 / 9.0.",
                "fahr = float(raw_fahr); return (fahr - 32.0) * 5.0 / 9.0",
            ],
            "skill_tags": ["input", "conversion", "floats", "arithmetic"],
            "source_citation": "PY4E Ch2 §2.10 'Asking the user for input' (temperature conversion).",
            "time_budget_min": 5,
            "difficulty_layer": 2,
        },
    ]


def _fixture_drills_chapter3() -> list[dict[str, Any]]:
    """Hand-transcribed drills for PY4E Chapter 3 §3.1–3.7."""

    return [
        {
            "slug": "check-equality",
            "title": "Compare two values for equality",
            "why_it_matters": (
                "Boolean expressions are the entry point to conditionals. "
                "The double-equals operator is the first big habit shift."
            ),
            "starter_code": (
                "def same_value(a: int, b: int) -> bool:\n"
                "    # TODO: return True when a and b are equal\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import same_value\n\n"
                "def test_equal_numbers():\n"
                "    assert same_value(5, 5) is True\n\n"
                "def test_different_numbers():\n"
                "    assert same_value(5, 6) is False\n"
            ),
            "reference_solution": (
                "def same_value(a: int, b: int) -> bool:\n    return a == b\n"
            ),
            "hints": [
                "Use == for comparison, not =.",
                "The result should already be a boolean.",
                "return a == b",
            ],
            "skill_tags": ["booleans", "comparison"],
            "source_citation": "PY4E Ch3 §3.1 'Boolean expressions' (5 == 5 / 5 == 6).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "check-not-equal",
            "title": "Check whether two values differ",
            "why_it_matters": (
                "Chapter 3 introduces the family of comparison operators. "
                "!= is a useful contrast to = and ==."
            ),
            "starter_code": (
                "def different(a: int, b: int) -> bool:\n"
                "    # TODO: return True when a and b are not equal\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import different\n\n"
                "def test_same():\n"
                "    assert different(4, 4) is False\n\n"
                "def test_diff():\n"
                "    assert different(4, 9) is True\n"
            ),
            "reference_solution": (
                "def different(a: int, b: int) -> bool:\n    return a != b\n"
            ),
            "hints": [
                "Use != for 'not equal'.",
                "Return the comparison directly.",
                "return a != b",
            ],
            "skill_tags": ["booleans", "comparison"],
            "source_citation": "PY4E Ch3 §3.1 'Boolean expressions' (comparison operator list).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "positive-single-digit",
            "title": "Check for a positive single-digit number",
            "why_it_matters": (
                "Logical operators let you combine two small facts into one condition. "
                "This is the book's own simplification example."
            ),
            "starter_code": (
                "def is_positive_single_digit(x: int) -> bool:\n"
                "    # TODO: return True only when x is greater than 0 and less than 10\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import is_positive_single_digit\n\n"
                "def test_true_case():\n"
                "    assert is_positive_single_digit(7) is True\n\n"
                "def test_zero_case():\n"
                "    assert is_positive_single_digit(0) is False\n\n"
                "def test_two_digit_case():\n"
                "    assert is_positive_single_digit(12) is False\n"
            ),
            "reference_solution": (
                "def is_positive_single_digit(x: int) -> bool:\n"
                "    return 0 < x and x < 10\n"
            ),
            "hints": [
                "This needs two comparisons joined with and.",
                "Both conditions must be true at the same time.",
                "return 0 < x and x < 10",
            ],
            "skill_tags": ["booleans", "logical-operators", "and"],
            "source_citation": "PY4E Ch3 §3.2 'Logical operators' and §3.6 (0 < x and x < 10).",
            "time_budget_min": 3,
            "difficulty_layer": 2,
        },
        {
            "slug": "divisible-by-two-or-three",
            "title": "Check divisibility by 2 or 3",
            "why_it_matters": (
                "The or operator turns two alternatives into one readable test. "
                "It is one of the book's first boolean combinations."
            ),
            "starter_code": (
                "def divisible_by_2_or_3(n: int) -> bool:\n"
                "    # TODO: return True when n is divisible by 2 or by 3\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import divisible_by_2_or_3\n\n"
                "def test_divisible_by_two():\n"
                "    assert divisible_by_2_or_3(8) is True\n\n"
                "def test_divisible_by_three():\n"
                "    assert divisible_by_2_or_3(9) is True\n\n"
                "def test_neither():\n"
                "    assert divisible_by_2_or_3(5) is False\n"
            ),
            "reference_solution": (
                "def divisible_by_2_or_3(n: int) -> bool:\n"
                "    return n % 2 == 0 or n % 3 == 0\n"
            ),
            "hints": [
                "Use modulo to test divisibility.",
                "Join the two divisibility checks with or.",
                "return n % 2 == 0 or n % 3 == 0",
            ],
            "skill_tags": ["booleans", "logical-operators", "or", "modulo"],
            "source_citation": "PY4E Ch3 §3.2 'Logical operators' (n%2 == 0 or n%3 == 0).",
            "time_budget_min": 3,
            "difficulty_layer": 2,
        },
        {
            "slug": "negate-comparison",
            "title": "Negate a comparison with not",
            "why_it_matters": (
                "The not operator is small but important. "
                "It helps learners read boolean logic in both directions."
            ),
            "starter_code": (
                "def not_greater(x: int, y: int) -> bool:\n"
                "    # TODO: return True when x is NOT greater than y\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import not_greater\n\n"
                "def test_smaller():\n"
                "    assert not_greater(1, 2) is True\n\n"
                "def test_equal():\n"
                "    assert not_greater(2, 2) is True\n\n"
                "def test_larger():\n"
                "    assert not_greater(3, 2) is False\n"
            ),
            "reference_solution": (
                "def not_greater(x: int, y: int) -> bool:\n    return not (x > y)\n"
            ),
            "hints": [
                "Start by writing the comparison x > y.",
                "Wrap the comparison in not (...).",
                "return not (x > y)",
            ],
            "skill_tags": ["booleans", "logical-operators", "not"],
            "source_citation": "PY4E Ch3 §3.2 'Logical operators' (not (x > y)).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "sign-label",
            "title": "Label a number as positive or not positive",
            "why_it_matters": (
                "A simple if statement is the first real branch in Chapter 3. "
                "This drill keeps the branch tiny and visible."
            ),
            "starter_code": (
                "def sign_label(x: int) -> str:\n"
                "    # TODO: use an if statement and return 'positive' when x > 0, "
                "otherwise return 'not positive'\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import sign_label\n\n"
                "def test_positive():\n"
                "    assert sign_label(4) == 'positive'\n\n"
                "def test_zero():\n"
                "    assert sign_label(0) == 'not positive'\n\n"
                "def test_negative():\n"
                "    assert sign_label(-3) == 'not positive'\n"
            ),
            "reference_solution": (
                "def sign_label(x: int) -> str:\n"
                "    if x > 0:\n"
                "        return 'positive'\n"
                "    return 'not positive'\n"
            ),
            "hints": [
                "Check x > 0 in the if condition.",
                "Return from inside the if block for the positive case.",
                "if x > 0: return 'positive'; return 'not positive'",
            ],
            "skill_tags": ["conditionals", "if"],
            "source_citation": "PY4E Ch3 §3.3 'Conditional execution' (if x > 0: ...).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "even-or-odd-label",
            "title": "Choose between even and odd",
            "why_it_matters": (
                "Alternative execution is easier to learn on a binary example. "
                "Parity makes if/else feel concrete."
            ),
            "starter_code": (
                "def parity_label(x: int) -> str:\n"
                "    # TODO: return 'even' when x % 2 == 0, otherwise return 'odd'\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import parity_label\n\n"
                "def test_even():\n"
                "    assert parity_label(8) == 'even'\n\n"
                "def test_odd():\n"
                "    assert parity_label(7) == 'odd'\n"
            ),
            "reference_solution": (
                "def parity_label(x: int) -> str:\n"
                "    if x % 2 == 0:\n"
                "        return 'even'\n"
                "    return 'odd'\n"
            ),
            "hints": [
                "Start with the condition x % 2 == 0.",
                "Use if for one branch and the default return for the other.",
                "if x % 2 == 0: return 'even'; return 'odd'",
            ],
            "skill_tags": ["conditionals", "if-else", "modulo"],
            "source_citation": "PY4E Ch3 §3.4 'Alternative execution' (even vs odd example).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "compare-two-numbers",
            "title": "Compare two numbers with elif",
            "why_it_matters": (
                "Chained conditionals show how to handle more than two cases "
                "without nesting yourself into a corner."
            ),
            "starter_code": (
                "def compare_numbers(x: int, y: int) -> str:\n"
                "    # TODO: return 'less', 'greater', or 'equal'\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import compare_numbers\n\n"
                "def test_less():\n"
                "    assert compare_numbers(1, 3) == 'less'\n\n"
                "def test_greater():\n"
                "    assert compare_numbers(5, 2) == 'greater'\n\n"
                "def test_equal():\n"
                "    assert compare_numbers(4, 4) == 'equal'\n"
            ),
            "reference_solution": (
                "def compare_numbers(x: int, y: int) -> str:\n"
                "    if x < y:\n"
                "        return 'less'\n"
                "    elif x > y:\n"
                "        return 'greater'\n"
                "    return 'equal'\n"
            ),
            "hints": [
                "Check x < y first, then x > y, then the final fallback is equality.",
                "This is a good fit for if / elif / else.",
                "if x < y: ... elif x > y: ... else: ...",
            ],
            "skill_tags": ["conditionals", "elif", "comparison"],
            "source_citation": "PY4E Ch3 §3.5 'Chained conditionals' (less / greater / equal).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "safe-parse-float",
            "title": "Catch bad numeric input with try/except",
            "why_it_matters": (
                "The try/except section is about keeping a program calm when input "
                "goes wrong instead of crashing out."
            ),
            "starter_code": (
                "def safe_float(raw: str) -> float | None:\n"
                "    # TODO: return float(raw); if conversion fails, return None\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import safe_float\n\n"
                "def test_valid_integer_like_text():\n"
                "    assert safe_float('72') == 72.0\n\n"
                "def test_valid_decimal_text():\n"
                "    assert safe_float('98.6') == 98.6\n\n"
                "def test_invalid_text():\n"
                "    assert safe_float('fred') is None\n"
            ),
            "reference_solution": (
                "def safe_float(raw: str) -> float | None:\n"
                "    try:\n"
                "        return float(raw)\n"
                "    except ValueError:\n"
                "        return None\n"
            ),
            "hints": [
                "Put the float(raw) call inside a try block.",
                "Catch ValueError and return None.",
                "try: return float(raw) except ValueError: return None",
            ],
            "skill_tags": ["exceptions", "try-except", "conversion"],
            "source_citation": "PY4E Ch3 §3.7 'Catching exceptions using try and except'.",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "fahrenheit-or-message",
            "title": "Return Celsius or a friendly message",
            "why_it_matters": (
                "This combines conversion, arithmetic, and exception handling into "
                "the same flow the chapter uses for its safe temperature example."
            ),
            "starter_code": (
                "def convert_or_message(raw: str) -> str:\n"
                "    # TODO: return the Celsius temperature as text, or 'Please enter a number'\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import convert_or_message\n\n"
                "def test_valid_value():\n"
                "    assert convert_or_message('32') == '0.0'\n\n"
                "def test_valid_decimal():\n"
                "    assert convert_or_message('212') == '100.0'\n\n"
                "def test_invalid_value():\n"
                "    assert convert_or_message('fred') == 'Please enter a number'\n"
            ),
            "reference_solution": (
                "def convert_or_message(raw: str) -> str:\n"
                "    try:\n"
                "        fahr = float(raw)\n"
                "        cel = (fahr - 32.0) * 5.0 / 9.0\n"
                "        return str(cel)\n"
                "    except ValueError:\n"
                "        return 'Please enter a number'\n"
            ),
            "hints": [
                "Start exactly like the Fahrenheit example: try to parse the text as a float.",
                "On success, compute Celsius and wrap it with str(...).",
                "Use try/except ValueError with the fallback message.",
            ],
            "skill_tags": ["exceptions", "try-except", "conversion", "conditionals"],
            "source_citation": "PY4E Ch3 §3.7 'Catching exceptions using try and except' (fahren2.py).",
            "time_budget_min": 5,
            "difficulty_layer": 3,
        },
    ]


def _fixture_drills_chapter4() -> list[dict[str, Any]]:
    """Hand-transcribed drills for PY4E Chapter 4 §4.1–4.8."""

    return [
        {
            "slug": "max-of-two",
            "title": "Use max to pick the larger value",
            "why_it_matters": (
                "Chapter 4 starts with function calls. "
                "max(...) is a clean first example of passing arguments to a function."
            ),
            "starter_code": (
                "def larger(a: int, b: int) -> int:\n"
                "    # TODO: return the larger of a and b using max()\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import larger\n\n"
                "def test_first_is_larger():\n"
                "    assert larger(9, 4) == 9\n\n"
                "def test_second_is_larger():\n"
                "    assert larger(3, 12) == 12\n"
            ),
            "reference_solution": (
                "def larger(a: int, b: int) -> int:\n    return max(a, b)\n"
            ),
            "hints": [
                "The built-in max() function returns the largest argument.",
                "Pass both numbers into max(...).",
                "return max(a, b)",
            ],
            "skill_tags": ["functions", "builtins", "max"],
            "source_citation": "PY4E Ch4 §4.2 'Built-in functions' (max examples).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "min-character",
            "title": "Find the smallest character in a string",
            "why_it_matters": (
                "The chapter shows built-in functions operating on strings too, "
                "which broadens what learners think a function can do."
            ),
            "starter_code": (
                "def smallest_char(text: str) -> str:\n"
                "    # TODO: return the smallest character in text using min()\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import smallest_char\n\n"
                "def test_simple_word():\n"
                "    assert smallest_char('banana') == 'a'\n\n"
                "def test_space_counts():\n"
                "    assert smallest_char('Hi there') == ' '\n"
            ),
            "reference_solution": (
                "def smallest_char(text: str) -> str:\n    return min(text)\n"
            ),
            "hints": [
                "min() also works on strings.",
                "Return the result directly.",
                "return min(text)",
            ],
            "skill_tags": ["functions", "builtins", "min", "strings"],
            "source_citation": "PY4E Ch4 §4.2 'Built-in functions' (min('Hello world')).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "string-length",
            "title": "Measure a string with len",
            "why_it_matters": (
                "len(...) is one of the core built-ins learners will use constantly. "
                "It anchors the idea that functions can return counts."
            ),
            "starter_code": (
                "def count_chars(text: str) -> int:\n"
                "    # TODO: return the number of characters in text\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import count_chars\n\n"
                "def test_word():\n"
                "    assert count_chars('Hello') == 5\n\n"
                "def test_with_space():\n"
                "    assert count_chars('Hi there') == 8\n"
            ),
            "reference_solution": (
                "def count_chars(text: str) -> int:\n    return len(text)\n"
            ),
            "hints": [
                "Use the built-in len() function.",
                "Spaces count as characters too.",
                "return len(text)",
            ],
            "skill_tags": ["functions", "builtins", "len"],
            "source_citation": "PY4E Ch4 §4.2 'Built-in functions' (len('Hello world')).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "parse-integer-text",
            "title": "Convert numeric text with int",
            "why_it_matters": (
                "Type conversion functions are central to Chapter 4. "
                "This drill keeps the learner focused on one clean conversion."
            ),
            "starter_code": (
                "def parse_int_text(raw: str) -> int:\n"
                "    # TODO: convert raw to an integer and return it\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import parse_int_text\n\n"
                "def test_simple():\n"
                "    assert parse_int_text('32') == 32\n\n"
                "def test_zero():\n"
                "    assert parse_int_text('0') == 0\n"
            ),
            "reference_solution": (
                "def parse_int_text(raw: str) -> int:\n    return int(raw)\n"
            ),
            "hints": [
                "Use the int() conversion function.",
                "The input is a string, not a number yet.",
                "return int(raw)",
            ],
            "skill_tags": ["functions", "type-conversion", "int"],
            "source_citation": "PY4E Ch4 §4.3 'Type conversion functions' (int('32')).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "truncate-float-with-int",
            "title": "Truncate a float with int",
            "why_it_matters": (
                "The chapter explicitly notes that int(...) chops off the fraction part "
                "instead of rounding. That distinction matters."
            ),
            "starter_code": (
                "def chop_fraction(value: float) -> int:\n"
                "    # TODO: convert value to an integer using int()\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import chop_fraction\n\n"
                "def test_positive_float():\n"
                "    assert chop_fraction(3.99999) == 3\n\n"
                "def test_negative_float():\n"
                "    assert chop_fraction(-2.3) == -2\n"
            ),
            "reference_solution": (
                "def chop_fraction(value: float) -> int:\n    return int(value)\n"
            ),
            "hints": [
                "Use int(...) on the float directly.",
                "This truncates toward zero; it does not round.",
                "return int(value)",
            ],
            "skill_tags": ["functions", "type-conversion", "int", "floats"],
            "source_citation": "PY4E Ch4 §4.3 'Type conversion functions' (int(3.99999), int(-2.3)).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "text-to-float",
            "title": "Convert text to a float",
            "why_it_matters": (
                "float(...) is the other half of basic numeric parsing. "
                "It helps learners stop treating decimal text as 'already a number'."
            ),
            "starter_code": (
                "def parse_float_text(raw: str) -> float:\n"
                "    # TODO: convert raw to a float and return it\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import parse_float_text\n\n"
                "def test_decimal_text():\n"
                "    assert abs(parse_float_text('3.14159') - 3.14159) < 1e-9\n\n"
                "def test_integer_like_text():\n"
                "    assert parse_float_text('32') == 32.0\n"
            ),
            "reference_solution": (
                "def parse_float_text(raw: str) -> float:\n    return float(raw)\n"
            ),
            "hints": [
                "Use float(...), not int(...).",
                "The return value should be a float.",
                "return float(raw)",
            ],
            "skill_tags": ["functions", "type-conversion", "float"],
            "source_citation": "PY4E Ch4 §4.3 'Type conversion functions' (float('3.14159')).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "number-to-string",
            "title": "Convert a number to text",
            "why_it_matters": (
                "str(...) completes the basic type-conversion trio. "
                "This is useful before printing or concatenating."
            ),
            "starter_code": (
                "def stringify(value: float) -> str:\n"
                "    # TODO: convert value to a string and return it\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import stringify\n\n"
                "def test_integer_value():\n"
                "    assert stringify(32) == '32'\n\n"
                "def test_decimal_value():\n"
                "    assert stringify(3.14159) == '3.14159'\n"
            ),
            "reference_solution": (
                "def stringify(value: float) -> str:\n    return str(value)\n"
            ),
            "hints": [
                "Use str(...) to get text back from a number.",
                "Return the converted value directly.",
                "return str(value)",
            ],
            "skill_tags": ["functions", "type-conversion", "strings"],
            "source_citation": "PY4E Ch4 §4.3 'Type conversion functions' (str(32), str(3.14159)).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "degrees-to-radians",
            "title": "Convert degrees to radians with math.pi",
            "why_it_matters": (
                "The chapter's math section teaches both importing a module "
                "and using dot notation to access its values."
            ),
            "starter_code": (
                "import math\n\n"
                "def degrees_to_radians(degrees: float) -> float:\n"
                "    # TODO: convert degrees to radians using math.pi\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import degrees_to_radians\n\n"
                "def test_zero_degrees():\n"
                "    assert abs(degrees_to_radians(0) - 0.0) < 1e-9\n\n"
                "def test_180_degrees():\n"
                "    import math\n"
                "    assert abs(degrees_to_radians(180) - math.pi) < 1e-9\n"
            ),
            "reference_solution": (
                "import math\n\n"
                "def degrees_to_radians(degrees: float) -> float:\n"
                "    return degrees / 360.0 * 2 * math.pi\n"
            ),
            "hints": [
                "Import math once at the top of the file.",
                "The book's formula is degrees / 360.0 * 2 * math.pi.",
                "return degrees / 360.0 * 2 * math.pi",
            ],
            "skill_tags": ["functions", "modules", "math", "dot-notation"],
            "source_citation": "PY4E Ch4 §4.4 'Math functions' (degrees to radians).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "sine-from-degrees",
            "title": "Use math.sin on a degree input",
            "why_it_matters": (
                "This takes the radians conversion one step further and makes the learner "
                "compose two math ideas in one function."
            ),
            "starter_code": (
                "import math\n\n"
                "def sine_from_degrees(degrees: float) -> float:\n"
                "    # TODO: convert degrees to radians, then return math.sin(...)\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import sine_from_degrees\n\n"
                "def test_zero_degrees():\n"
                "    assert abs(sine_from_degrees(0) - 0.0) < 1e-9\n\n"
                "def test_45_degrees():\n"
                "    assert abs(sine_from_degrees(45) - 0.7071067811865476) < 1e-9\n"
            ),
            "reference_solution": (
                "import math\n\n"
                "def sine_from_degrees(degrees: float) -> float:\n"
                "    radians = degrees / 360.0 * 2 * math.pi\n"
                "    return math.sin(radians)\n"
            ),
            "hints": [
                "math.sin(...) expects radians, not degrees.",
                "Reuse the degrees-to-radians formula before calling math.sin.",
                "radians = degrees / 360.0 * 2 * math.pi; return math.sin(radians)",
            ],
            "skill_tags": ["functions", "modules", "math", "sin"],
            "source_citation": "PY4E Ch4 §4.4 'Math functions' (math.sin with radians).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "call-helper-function-twice",
            "title": "Define one function and call it from another",
            "why_it_matters": (
                "The chapter's big new move is not just using functions, "
                "but writing your own and reusing them."
            ),
            "starter_code": (
                "def shout_once(word: str) -> str:\n"
                "    # TODO: return word + '!'\n"
                "    ...\n\n"
                "def shout_twice(word: str) -> str:\n"
                "    # TODO: call shout_once(word) twice with a space between the results\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import shout_once, shout_twice\n\n"
                "def test_helper():\n"
                "    assert shout_once('Hi') == 'Hi!'\n\n"
                "def test_caller():\n"
                "    assert shout_twice('Hi') == 'Hi! Hi!'\n"
            ),
            "reference_solution": (
                "def shout_once(word: str) -> str:\n"
                "    return word + '!'\n\n"
                "def shout_twice(word: str) -> str:\n"
                "    return shout_once(word) + ' ' + shout_once(word)\n"
            ),
            "hints": [
                "Finish the small helper first.",
                "Then call the helper inside the second function instead of rewriting the logic.",
                "return shout_once(word) + ' ' + shout_once(word)",
            ],
            "skill_tags": ["functions", "definitions", "function-calls"],
            "source_citation": "PY4E Ch4 §4.6-4.8 'Adding new functions' and 'Flow of execution'.",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
    ]


def _fixture_drills_chapter5() -> list[dict[str, Any]]:
    """Hand-transcribed drills for PY4E Chapter 5 §5.1–5.6."""

    return [
        {
            "slug": "increment-value",
            "title": "Increment a value by one",
            "why_it_matters": (
                "Updating variables is the simplest loop-adjacent pattern in Chapter 5. "
                "It sets up how iteration variables change."
            ),
            "starter_code": (
                "def increment(x: int) -> int:\n"
                "    # TODO: return x updated by adding 1\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import increment\n\n"
                "def test_small_number():\n"
                "    assert increment(0) == 1\n\n"
                "def test_positive_number():\n"
                "    assert increment(9) == 10\n"
            ),
            "reference_solution": (
                "def increment(x: int) -> int:\n    x = x + 1\n    return x\n"
            ),
            "hints": [
                "Use x = x + 1 inside the function.",
                "Return the updated x.",
                "x = x + 1; return x",
            ],
            "skill_tags": ["iteration", "updating-variables"],
            "source_citation": "PY4E Ch5 §5.1 'Updating variables' (x = x + 1).",
            "time_budget_min": 2,
            "difficulty_layer": 1,
        },
        {
            "slug": "countdown-list",
            "title": "Build a countdown with while",
            "why_it_matters": (
                "The countdown example is the chapter's first full while loop. "
                "Turning it into a list keeps it testable."
            ),
            "starter_code": (
                "def countdown(n: int) -> list[int | str]:\n"
                "    # TODO: use a while loop to collect n, n-1, ..., 1, then 'Blastoff!'\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import countdown\n\n"
                "def test_three():\n"
                "    assert countdown(3) == [3, 2, 1, 'Blastoff!']\n\n"
                "def test_one():\n"
                "    assert countdown(1) == [1, 'Blastoff!']\n"
            ),
            "reference_solution": (
                "def countdown(n: int) -> list[int | str]:\n"
                "    out: list[int | str] = []\n"
                "    while n > 0:\n"
                "        out.append(n)\n"
                "        n = n - 1\n"
                "    out.append('Blastoff!')\n"
                "    return out\n"
            ),
            "hints": [
                "Start with an empty list like out = [].",
                "Append n inside the loop, then decrement n.",
                "Use while n > 0: ... and append 'Blastoff!' after the loop.",
            ],
            "skill_tags": ["iteration", "while-loop"],
            "source_citation": "PY4E Ch5 §5.2 'The while statement' (countdown / Blastoff).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "copy-until-done",
            "title": "Stop copying when you read done",
            "why_it_matters": (
                "The chapter's deliberate infinite loop becomes useful only when break "
                "creates a clear exit condition."
            ),
            "starter_code": (
                "def copy_until_done(lines: list[str]) -> list[str]:\n"
                "    # TODO: return every line until 'done' appears; do not include 'done'\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import copy_until_done\n\n"
                "def test_stops_on_done():\n"
                "    assert copy_until_done(['hello', 'there', 'done', 'later']) == ['hello', 'there']\n\n"
                "def test_done_first():\n"
                "    assert copy_until_done(['done', 'later']) == []\n"
            ),
            "reference_solution": (
                "def copy_until_done(lines: list[str]) -> list[str]:\n"
                "    out: list[str] = []\n"
                "    index = 0\n"
                "    while True:\n"
                "        line = lines[index]\n"
                "        index += 1\n"
                "        if line == 'done':\n"
                "            break\n"
                "        out.append(line)\n"
                "    return out\n"
            ),
            "hints": [
                "This is the 'while True' plus break pattern from the book.",
                "Read one item each iteration and break on 'done'.",
                "if line == 'done': break",
            ],
            "skill_tags": ["iteration", "while-loop", "break"],
            "source_citation": "PY4E Ch5 §5.3 'Infinite loops' (copytildone1.py).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "skip-hash-lines",
            "title": "Skip comment-style lines with continue",
            "why_it_matters": (
                "continue is easiest to understand when it visibly skips one class of input "
                "but keeps the loop alive."
            ),
            "starter_code": (
                "def visible_lines(lines: list[str]) -> list[str]:\n"
                "    # TODO: skip lines starting with '#', stop on 'done', return the rest\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import visible_lines\n\n"
                "def test_skips_hash_lines():\n"
                "    lines = ['hello', '# comment', 'print this', 'done', 'later']\n"
                "    assert visible_lines(lines) == ['hello', 'print this']\n\n"
                "def test_only_done():\n"
                "    assert visible_lines(['done']) == []\n"
            ),
            "reference_solution": (
                "def visible_lines(lines: list[str]) -> list[str]:\n"
                "    out: list[str] = []\n"
                "    index = 0\n"
                "    while True:\n"
                "        line = lines[index]\n"
                "        index += 1\n"
                "        if line.startswith('#'):\n"
                "            continue\n"
                "        if line == 'done':\n"
                "            break\n"
                "        out.append(line)\n"
                "    return out\n"
            ),
            "hints": [
                "Use continue for lines that start with '#'.",
                "The done check should still break out of the loop.",
                "if line.startswith('#'): continue",
            ],
            "skill_tags": ["iteration", "while-loop", "continue"],
            "source_citation": "PY4E Ch5 §5.4 'Finishing iterations with continue' (copytildone2.py).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "greet-friends-loop",
            "title": "Loop through friends with for",
            "why_it_matters": (
                "The first for-loop example is a direct contrast with while: "
                "iterate over known items instead of waiting on a condition."
            ),
            "starter_code": (
                "def greet_friends(friends: list[str]) -> list[str]:\n"
                "    # TODO: return ['Happy New Year: <name>', ...] for each friend\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import greet_friends\n\n"
                "def test_three_names():\n"
                "    assert greet_friends(['Joseph', 'Glenn', 'Sally']) == [\n"
                "        'Happy New Year: Joseph',\n"
                "        'Happy New Year: Glenn',\n"
                "        'Happy New Year: Sally',\n"
                "    ]\n\n"
                "def test_empty_list():\n"
                "    assert greet_friends([]) == []\n"
            ),
            "reference_solution": (
                "def greet_friends(friends: list[str]) -> list[str]:\n"
                "    out: list[str] = []\n"
                "    for friend in friends:\n"
                "        out.append(f'Happy New Year: {friend}')\n"
                "    return out\n"
            ),
            "hints": [
                "Start with an empty list.",
                "Use a for friend in friends loop.",
                "Append one greeting per friend.",
            ],
            "skill_tags": ["iteration", "for-loop", "lists"],
            "source_citation": "PY4E Ch5 §5.5 'Definite loops using for' (Happy New Year example).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "count-loop-items",
            "title": "Count items with an accumulator",
            "why_it_matters": (
                "Counting is the book's first loop pattern. "
                "It shows what 'running total so far' looks like in practice."
            ),
            "starter_code": (
                "def count_values(values: list[int]) -> int:\n"
                "    # TODO: count how many items are in values using a loop\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import count_values\n\n"
                "def test_many_items():\n"
                "    assert count_values([3, 41, 12, 9, 74, 15]) == 6\n\n"
                "def test_empty_items():\n"
                "    assert count_values([]) == 0\n"
            ),
            "reference_solution": (
                "def count_values(values: list[int]) -> int:\n"
                "    count = 0\n"
                "    for _ in values:\n"
                "        count = count + 1\n"
                "    return count\n"
            ),
            "hints": [
                "Initialize count = 0 before the loop.",
                "Add 1 each iteration.",
                "Use count = count + 1 inside the loop.",
            ],
            "skill_tags": ["iteration", "loop-patterns", "counting"],
            "source_citation": "PY4E Ch5 §5.6.1 'Counting and summing loops' (count pattern).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "sum-loop-values",
            "title": "Sum values with an accumulator",
            "why_it_matters": (
                "Summing is the next natural loop pattern after counting. "
                "It teaches how the current item changes the running result."
            ),
            "starter_code": (
                "def total_values(values: list[int]) -> int:\n"
                "    # TODO: return the sum of values using a loop\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import total_values\n\n"
                "def test_many_items():\n"
                "    assert total_values([3, 41, 12, 9, 74, 15]) == 154\n\n"
                "def test_empty_items():\n"
                "    assert total_values([]) == 0\n"
            ),
            "reference_solution": (
                "def total_values(values: list[int]) -> int:\n"
                "    total = 0\n"
                "    for value in values:\n"
                "        total = total + value\n"
                "    return total\n"
            ),
            "hints": [
                "Initialize total = 0 before the loop.",
                "Add the current value during each iteration.",
                "total = total + value",
            ],
            "skill_tags": ["iteration", "loop-patterns", "accumulator"],
            "source_citation": "PY4E Ch5 §5.6.1 'Counting and summing loops' (total pattern).",
            "time_budget_min": 3,
            "difficulty_layer": 1,
        },
        {
            "slug": "largest-value-loop",
            "title": "Track the largest value seen so far",
            "why_it_matters": (
                "The maximum loop is the chapter's most important stateful pattern. "
                "It teaches how None can mark an empty start."
            ),
            "starter_code": (
                "def largest_value(values: list[int]) -> int | None:\n"
                "    # TODO: return the largest number in values, or None if values is empty\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import largest_value\n\n"
                "def test_many_items():\n"
                "    assert largest_value([3, 41, 12, 9, 74, 15]) == 74\n\n"
                "def test_single_item():\n"
                "    assert largest_value([7]) == 7\n\n"
                "def test_empty_items():\n"
                "    assert largest_value([]) is None\n"
            ),
            "reference_solution": (
                "def largest_value(values: list[int]) -> int | None:\n"
                "    largest = None\n"
                "    for value in values:\n"
                "        if largest is None or value > largest:\n"
                "            largest = value\n"
                "    return largest\n"
            ),
            "hints": [
                "Start with largest = None.",
                "Update largest when it is None or when the new value is bigger.",
                "if largest is None or value > largest: largest = value",
            ],
            "skill_tags": ["iteration", "loop-patterns", "maximum", "none"],
            "source_citation": "PY4E Ch5 §5.6.2 'Maximum and minimum loops' (largest so far).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "smallest-value-loop",
            "title": "Track the smallest value seen so far",
            "why_it_matters": (
                "Once learners understand the maximum pattern, the minimum pattern "
                "helps them see the reusable shape under the loop."
            ),
            "starter_code": (
                "def smallest_value(values: list[int]) -> int | None:\n"
                "    # TODO: return the smallest number in values, or None if values is empty\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import smallest_value\n\n"
                "def test_many_items():\n"
                "    assert smallest_value([3, 41, 12, 9, 74, 15]) == 3\n\n"
                "def test_negative_item():\n"
                "    assert smallest_value([5, -2, 8]) == -2\n\n"
                "def test_empty_items():\n"
                "    assert smallest_value([]) is None\n"
            ),
            "reference_solution": (
                "def smallest_value(values: list[int]) -> int | None:\n"
                "    smallest = None\n"
                "    for value in values:\n"
                "        if smallest is None or value < smallest:\n"
                "            smallest = value\n"
                "    return smallest\n"
            ),
            "hints": [
                "This is the same pattern as largest_value, but with < instead of >.",
                "Start with smallest = None.",
                "if smallest is None or value < smallest: smallest = value",
            ],
            "skill_tags": ["iteration", "loop-patterns", "minimum", "none"],
            "source_citation": "PY4E Ch5 §5.6.2 'Maximum and minimum loops' (minimum twin of largest loop).",
            "time_budget_min": 4,
            "difficulty_layer": 2,
        },
        {
            "slug": "average-from-loop",
            "title": "Compute an average from count and total",
            "why_it_matters": (
                "This combines two chapter patterns — counting and summing — "
                "into one small, useful result."
            ),
            "starter_code": (
                "def average_values(values: list[int]) -> float | None:\n"
                "    # TODO: return the average of values, or None if values is empty\n"
                "    ...\n"
            ),
            "hidden_tests": (
                "from solution import average_values\n\n"
                "def test_many_items():\n"
                "    assert abs(average_values([3, 41, 12, 9, 74, 15]) - 25.666666666666668) < 1e-9\n\n"
                "def test_small_list():\n"
                "    assert average_values([2, 4]) == 3.0\n\n"
                "def test_empty_items():\n"
                "    assert average_values([]) is None\n"
            ),
            "reference_solution": (
                "def average_values(values: list[int]) -> float | None:\n"
                "    if not values:\n"
                "        return None\n"
                "    total = 0\n"
                "    count = 0\n"
                "    for value in values:\n"
                "        total = total + value\n"
                "        count = count + 1\n"
                "    return total / count\n"
            ),
            "hints": [
                "You need both a running total and a running count.",
                "Handle the empty list first so you do not divide by zero.",
                "total / count gives the final average.",
            ],
            "skill_tags": ["iteration", "loop-patterns", "counting", "accumulator"],
            "source_citation": "PY4E Ch5 §5.6 'Loop patterns' (counting + summing composition).",
            "time_budget_min": 5,
            "difficulty_layer": 3,
        },
    ]


def _fallback_fixture_drills(chapter: int) -> list[dict[str, Any]]:
    """Return deterministic hand-authored drills for early PY4E chapters."""

    fixtures: dict[int, list[dict[str, Any]]] = {
        1: _fixture_drills_chapter1(),
        2: _fixture_drills_chapter2(),
        3: _fixture_drills_chapter3(),
        4: _fixture_drills_chapter4(),
        5: _fixture_drills_chapter5(),
    }
    if chapter not in fixtures:
        raise RuntimeError(
            "fallback fixture currently covers chapters 1-5 only; "
            f"got --chapter {chapter}. Set GROQ_API_KEY to use the LLM path "
            "for later chapters."
        )
    return fixtures[chapter]


# ── Assemble + write ────────────────────────────────────────────────


def build_course_doc(
    course_slug: str,
    course_title: str,
    source_label: str,
    version: str,
    chapter: int,
    chapter_title: str,
    drills: list[dict[str, Any]],
    course_description: str | None = None,
    estimated_hours: int = 12,
    module_slug_prefix: str = "ch",
    module_label: str = "Chapter",
) -> dict[str, Any]:
    """Wrap a validated drill list into the loader's course.yaml shape.

    ``services.drill_loader.load_course`` expects the course metadata at
    the YAML root, not nested under ``course:``. One transpiler run
    emits one module; :func:`merge_into_existing` handles stitching
    additional chapters into the same file later.
    """

    module_slug = f"{module_slug_prefix}{chapter:02d}"
    description = course_description or (
        "Short, checked Python drills compiled from the PY4E book. "
        "Each drill focuses on one small idea and keeps the theory on demand."
    )
    return {
        "slug": course_slug,
        "title": course_title,
        "source": source_label,
        "version": version,
        "description": description,
        "estimated_hours": estimated_hours,
        "modules": [
            {
                "slug": module_slug,
                "title": f"{module_label} {chapter}: {chapter_title}",
                "order_index": chapter,
                "outcome": (
                    f"Practice the core ideas from {module_label} {chapter} of {course_title} "
                    "with short, test-backed drills."
                ),
                "drills": drills,
            }
        ],
    }


def merge_into_existing(
    existing: dict[str, Any], new_doc: dict[str, Any]
) -> dict[str, Any]:
    """Merge ``new_doc`` into ``existing`` by replacing modules sharing a slug.

    Idempotent: re-running the transpiler for chapter 1 overwrites
    ``ch01`` in place instead of appending a second copy. Modules are
    then sorted by ``order_index`` so the output YAML is stable.
    """

    base = dict(existing)
    incoming = new_doc

    # Trust the newest metadata — caller passed matching values anyway,
    # but if the course title/version changed, the incoming document wins.
    for key in (
        "slug",
        "title",
        "source",
        "version",
        "description",
        "estimated_hours",
    ):
        base[key] = incoming[key]

    existing_modules = {m["slug"]: m for m in base.get("modules", [])}
    for module in incoming.get("modules", []):
        existing_modules[module["slug"]] = module
    base["modules"] = sorted(
        existing_modules.values(), key=lambda m: m.get("order_index", 0)
    )
    return base


def write_yaml(path: Path, doc: dict[str, Any]) -> int:
    """Write ``doc`` as YAML and return bytes written.

    Uses ``default_flow_style=False`` and ``sort_keys=False`` so the
    output stays in the intentional key order (course → modules →
    drills) and reads as a block-style document — the committed form we
    want humans to review on day 4.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        doc,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


# ── Main pipeline ───────────────────────────────────────────────────


async def transpile(args: argparse.Namespace) -> None:
    """End-to-end: extract → LLM (or fixture) → validate → gate → write."""

    source_path = Path(args.source).resolve()
    output_path = Path(args.output).resolve()
    source_spec = _get_course_source_spec(args.course_slug)

    if not source_path.exists():
        raise FileNotFoundError(f"source not found: {source_path}")

    module_label = source_spec["module_label"]
    chapter_title = source_spec["unit_titles"].get(
        args.chapter,
        f"{module_label} {args.chapter}",
    )

    # --- Step 1: extract or skip ---
    provider_specs = _available_provider_specs()
    use_fallback = args.dry_run or not provider_specs
    if use_fallback:
        reason = (
            "--dry-run"
            if args.dry_run
            else "no GROQ_API_KEY / OPENAI_API_KEY configured"
        )
        print(f"[transpile] fallback path: {reason}")
        if args.course_slug != "py4e":
            raise RuntimeError(
                f"fallback fixtures currently exist only for 'py4e'; "
                f"configure GROQ_API_KEY or OPENAI_API_KEY to compile {args.course_slug!r}"
            )
        candidates = _fallback_fixture_drills(args.chapter)
    else:
        source_kind = str(source_spec["source_kind"]).upper()
        print(
            f"[transpile] extracting {module_label.lower()} {args.chapter} "
            f"text from {source_kind} source..."
        )
        chapter_text = extract_source_unit_text(
            source_path,
            args.course_slug,
            args.chapter,
        )
        print(
            f"[transpile] extracted {len(chapter_text)} chars; "
            "calling provider chain (Groq primary -> OpenAI fallback)..."
        )
        provider_name, candidates = call_llm(
            course_title=args.course_title,
            unit_label=module_label,
            unit_number=args.chapter,
            unit_title=chapter_title,
            unit_text=chapter_text,
            n_drills=args.drills_per_chapter,
            citation_example=str(source_spec["citation_example"]),
        )
        print(
            f"[transpile] {provider_name} returned {len(candidates)} candidate drills"
        )

    # --- Step 2: shape validation ---
    shaped: list[dict[str, Any]] = []
    for idx, drill in enumerate(candidates):
        errs = validate_drill_shape(drill)
        if errs:
            slug = drill.get("slug", f"<idx {idx}>")
            print(f"[transpile] SKIP (shape) {slug}: {errs}")
            continue
        shaped.append(drill)
    print(f"[transpile] {len(shaped)}/{len(candidates)} drills passed shape gate")

    # --- Step 3: reference-solution sandbox gate ---
    survivors: list[dict[str, Any]] = []
    rejected: list[tuple[str, str]] = []
    for drill in shaped:
        passed, output = await gate_drill(drill)
        if not passed:
            rejected.append((drill["slug"], output[:400]))
            print(
                f"[transpile] REJECT (ref-sol failed its own tests) "
                f"{drill['slug']}: {output[:200]}"
            )
            continue
        survivors.append(drill)
    total_candidates = len(shaped) or 1
    pct_rejected = 100 * len(rejected) / total_candidates
    print(
        f"[transpile] {len(survivors)}/{len(shaped)} drills passed ref-sol gate "
        f"({pct_rejected:.0f}% rejected)"
    )

    if not survivors:
        raise RuntimeError(
            "No drills survived the reference-solution gate — aborting "
            "before writing an empty/invalid YAML."
        )

    # --- Step 4: set order_index + assemble ---
    for i, drill in enumerate(survivors, start=1):
        drill["order_index"] = i

    new_doc = build_course_doc(
        course_slug=args.course_slug,
        course_title=args.course_title,
        source_label=args.source_label,
        version=args.version,
        chapter=args.chapter,
        chapter_title=chapter_title,
        drills=survivors,
        course_description=str(source_spec["description"]),
        estimated_hours=int(source_spec["estimated_hours"]),
        module_slug_prefix=str(source_spec["module_slug_prefix"]),
        module_label=module_label,
    )

    # --- Step 5: merge or write ---
    if output_path.is_file():
        with output_path.open(encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
        doc = merge_into_existing(existing, new_doc)
    else:
        doc = new_doc

    bytes_written = write_yaml(output_path, doc)
    print(
        f"[transpile] wrote {output_path} "
        f"({bytes_written} bytes, {len(survivors)} drills in {module_label.lower()} {args.chapter})"
    )


def _parse_args() -> argparse.Namespace:
    """Argparse setup; kept tiny — all flags map 1:1 onto the module docstring."""

    p = argparse.ArgumentParser(
        description="Transpile one source unit into compiled drill YAML."
    )
    p.add_argument(
        "--source",
        required=True,
        help="Path to the source file or source directory (for HTML-backed courses).",
    )
    p.add_argument("--course-slug", required=True, help="Short course slug (py4e).")
    p.add_argument("--course-title", required=True, help="Human course title.")
    p.add_argument(
        "--source-label",
        required=True,
        help="Source-origin label written to course.yaml 'source' (e.g. py4e).",
    )
    p.add_argument("--version", default="v1.0.0", help="Content version tag.")
    p.add_argument("--chapter", type=int, required=True, help="Chapter number.")
    p.add_argument(
        "--drills-per-chapter",
        type=int,
        default=10,
        help="Target drill count for the LLM call (fixture path ignores this).",
    )
    p.add_argument("--output", required=True, help="Destination course.yaml path.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip LLM providers; emit deterministic fixture drills instead.",
    )
    return p.parse_args()


def main() -> None:
    """CLI entry point; runs the async :func:`transpile`."""

    args = _parse_args()
    asyncio.run(transpile(args))


if __name__ == "__main__":
    main()
