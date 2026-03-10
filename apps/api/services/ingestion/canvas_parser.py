"""Canvas content parsing and extraction utilities.

Data structures and parsers for Canvas LMS content:
- CanvasExtraction dataclass for deep extraction results
- Quiz question parsing into PracticeProblem-compatible dicts
- File URL extraction from Canvas HTML content

Extracted from canvas_loader.py.
"""

import re
from dataclasses import dataclass, field


@dataclass
class CanvasExtraction:
    """Result of deep Canvas API extraction."""
    title: str
    content: str
    file_urls: list[dict] = field(default_factory=list)
    pages_fetched: int = 0
    modules_found: int = 0
    quiz_questions: list[dict] = field(default_factory=list)
    assignments_data: list[dict] = field(default_factory=list)


def _parse_canvas_quiz_question(question: dict, quiz_title: str) -> dict | None:
    """Parse a Canvas API quiz question into a PracticeProblem-compatible dict."""
    from bs4 import BeautifulSoup

    q_text = question.get("question_text", "")
    if not q_text:
        return None
    soup = BeautifulSoup(q_text, "lxml")
    clean_text = soup.get_text(strip=True)
    if not clean_text:
        return None

    canvas_type = question.get("question_type", "")
    TYPE_MAP = {
        "multiple_choice_question": "mc",
        "true_false_question": "tf",
        "short_answer_question": "short_answer",
        "multiple_answers_question": "select_all",
        "fill_in_multiple_blanks_question": "fill_blank",
        "essay_question": "free_response",
        "matching_question": "matching",
    }
    question_type = TYPE_MAP.get(canvas_type, "mc")

    answers = question.get("answers", [])
    options = None
    correct_answer = None

    if question_type in ("mc", "tf", "select_all"):
        options = {}
        correct_keys = []
        for i, ans in enumerate(answers):
            key = chr(ord("A") + i) if i < 26 else str(i + 1)
            ans_text = ans.get("text", "") or ans.get("html", "")
            if ans_text:
                if not ans.get("text") and ans.get("html"):
                    s = BeautifulSoup(ans_text, "lxml")
                    ans_text = s.get_text(strip=True)
                options[key] = ans_text
                weight = ans.get("weight", 0)
                if weight and float(weight) > 0:
                    correct_keys.append(key)
        correct_answer = ",".join(correct_keys) if correct_keys else None
    elif question_type == "short_answer":
        for ans in answers:
            ans_text = ans.get("text", "")
            weight = ans.get("weight", 0)
            if ans_text and weight and float(weight) > 0:
                correct_answer = ans_text
                break

    return {
        "question_type": question_type,
        "question": clean_text,
        "options": options,
        "correct_answer": correct_answer,
        "explanation": None,
        "difficulty_layer": 2,
        "problem_metadata": {
            "core_concept": quiz_title,
            "bloom_level": "understand",
            "potential_traps": [],
            "layer_justification": "Imported from Canvas quiz",
            "skill_focus": "concept check",
            "source_section": quiz_title,
            "source_kind": "canvas_import",
        },
    }


def _extract_file_urls_from_html(
    html: str,
    base_url: str,
    module_name: str | None = None,
    item_title: str | None = None,
) -> list[dict]:
    """Extract PDF and document file URLs from Canvas page HTML body."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse
    from pathlib import Path

    soup = BeautifulSoup(html, "lxml")
    files: list[dict] = []
    seen_urls: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)

        if full_url in seen_urls:
            continue

        is_canvas_file = bool(re.search(r"/files/\d+", href))
        parsed = urlparse(full_url)
        ext = Path(parsed.path).suffix.lower()
        is_doc_link = ext in {".pdf", ".doc", ".docx", ".pptx", ".ppt", ".xlsx", ".xls"}

        if is_canvas_file or is_doc_link:
            seen_urls.add(full_url)
            link_text = a_tag.get_text(strip=True) or Path(parsed.path).stem
            download_url = full_url
            if is_canvas_file and "/download" not in full_url:
                clean = full_url.split("?")[0].rstrip("/")
                download_url = f"{clean}/download"

            filename = link_text
            if not any(filename.lower().endswith(e) for e in (".pdf", ".doc", ".docx", ".pptx")):
                filename = f"{link_text}{ext}" if ext else f"{link_text}.pdf"

            content_type = "application/pdf" if ext == ".pdf" or not ext else f"application/{ext.lstrip('.')}"
            entry = {
                "url": download_url,
                "display_url": full_url,
                "filename": filename,
                "content_type": content_type,
            }
            if module_name:
                entry["module_name"] = module_name
            if item_title:
                entry["item_title"] = item_title
            files.append(entry)

    return files
