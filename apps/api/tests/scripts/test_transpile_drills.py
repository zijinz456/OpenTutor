"""Regression tests for the drills transpiler contract.

The compiled ``course.yaml`` is consumed later by
``services.drill_loader.load_course``. These tests keep the transpiler's
root shape and chapter-merge semantics aligned with that loader so we do
not generate files that look valid but cannot be seeded.
"""

from __future__ import annotations

from pathlib import Path

import scripts.transpile_drills as transpile_drills
from scripts.transpile_drills import (
    CS50P_WEEK_FILES,
    CS50P_WEEK_TITLES,
    PY4E_CHAPTER_PAGES,
    PY4E_CHAPTER_TITLES,
    _fallback_fixture_drills,
    _fixture_drills_chapter1,
    _extract_main_html_text,
    build_course_doc,
    extract_source_unit_text,
    merge_into_existing,
)


def test_build_course_doc_matches_loader_root_shape():
    drills = _fixture_drills_chapter1()[:2]
    for index, drill in enumerate(drills, start=1):
        drill["order_index"] = index

    doc = build_course_doc(
        course_slug="py4e",
        course_title="Python for Everybody",
        source_label="py4e",
        version="v1.0.0",
        chapter=1,
        chapter_title="Why Should You Learn to Write Programs?",
        drills=drills,
    )

    assert "course" not in doc
    assert doc["slug"] == "py4e"
    assert doc["version"] == "v1.0.0"
    assert len(doc["modules"]) == 1
    assert doc["modules"][0]["order_index"] == 1
    assert doc["modules"][0]["drills"][0]["order_index"] == 1


def test_build_course_doc_supports_generic_module_labels():
    drills = _fixture_drills_chapter1()[:1]
    drills[0]["order_index"] = 1

    doc = build_course_doc(
        course_slug="cs50p",
        course_title="CS50's Introduction to Programming with Python",
        source_label="cs50p",
        version="v1.0.0",
        chapter=0,
        chapter_title="Functions, Variables",
        drills=drills,
        course_description=(
            "Short, checked Python drills compiled from CS50P lecture notes."
        ),
        estimated_hours=8,
        module_slug_prefix="wk",
        module_label="Week",
    )

    assert doc["description"] == (
        "Short, checked Python drills compiled from CS50P lecture notes."
    )
    assert doc["estimated_hours"] == 8
    assert doc["modules"][0]["slug"] == "wk00"
    assert doc["modules"][0]["title"] == "Week 0: Functions, Variables"
    assert "Week 0" in doc["modules"][0]["outcome"]


def test_merge_into_existing_replaces_same_module_slug_and_sorts():
    chapter2 = build_course_doc(
        course_slug="py4e",
        course_title="Python for Everybody",
        source_label="py4e",
        version="v1.0.0",
        chapter=2,
        chapter_title="Variables, Expressions, and Statements",
        drills=[],
    )
    chapter2["modules"][0]["drills"] = _fixture_drills_chapter1()[:1]
    chapter2["modules"][0]["drills"][0]["order_index"] = 1

    chapter1 = build_course_doc(
        course_slug="py4e",
        course_title="Python for Everybody",
        source_label="py4e",
        version="v1.0.0",
        chapter=1,
        chapter_title="Why Should You Learn to Write Programs?",
        drills=[],
    )
    chapter1["modules"][0]["drills"] = _fixture_drills_chapter1()[:1]
    chapter1["modules"][0]["drills"][0]["order_index"] = 1

    merged = merge_into_existing(chapter2, chapter1)

    assert [module["slug"] for module in merged["modules"]] == ["ch01", "ch02"]
    assert merged["slug"] == "py4e"
    assert merged["modules"][0]["order_index"] == 1
    assert merged["modules"][1]["order_index"] == 2


def test_fallback_fixtures_cover_first_five_chapters():
    for chapter in (1, 2, 3, 4, 5):
        drills = _fallback_fixture_drills(chapter)
        assert len(drills) == 10
        assert all("slug" in drill for drill in drills)


def test_provider_specs_prefer_groq_then_openai(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setattr(transpile_drills.settings, "groq_api_key", "")
    monkeypatch.setattr(transpile_drills.settings, "openai_api_key", "")

    specs = transpile_drills._available_provider_specs()

    assert [spec["provider"] for spec in specs] == ["groq", "openai"]
    assert specs[0]["model"] == transpile_drills._GROQ_MODEL
    assert specs[1]["model"] == transpile_drills._OPENAI_FALLBACK_MODEL


def test_py4e_chapter_metadata_covers_chapters_one_through_sixteen():
    chapters = list(range(1, 17))

    assert sorted(PY4E_CHAPTER_PAGES) == chapters
    assert sorted(PY4E_CHAPTER_TITLES) == chapters

    previous_end = -1
    for chapter in chapters:
        start, end = PY4E_CHAPTER_PAGES[chapter]
        assert start <= end
        assert start > previous_end
        assert PY4E_CHAPTER_TITLES[chapter]
        previous_end = end


def test_cs50p_week_metadata_covers_zero_through_two():
    weeks = [0, 1, 2]

    assert sorted(CS50P_WEEK_FILES) == weeks
    assert sorted(CS50P_WEEK_TITLES) == weeks
    assert all(CS50P_WEEK_FILES[week].endswith(".html") for week in weeks)
    assert all(CS50P_WEEK_TITLES[week] for week in weeks)


def test_extract_main_html_text_prefers_main_content(tmp_path: Path):
    html_path = tmp_path / "week_0.html"
    html_path.write_text(
        (
            "<html><body><nav>noise nav</nav><main>"
            "<h1>Week 0</h1><p>Hello functions</p>"
            "</main><footer>footer noise</footer></body></html>"
        ),
        encoding="utf-8",
    )

    text = _extract_main_html_text(html_path)

    assert "Week 0" in text
    assert "Hello functions" in text
    assert "noise nav" not in text


def test_extract_source_unit_text_reads_cs50p_week_file(tmp_path: Path):
    (tmp_path / "week_0.html").write_text(
        "<html><body><main><h1>Week 0</h1><p>Return values</p></main></body></html>",
        encoding="utf-8",
    )

    text = extract_source_unit_text(tmp_path, "cs50p", 0)

    assert "Week 0" in text
    assert "Return values" in text
