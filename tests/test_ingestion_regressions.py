import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.ingestion.document_loader import _crawl_result_to_extraction
from services.ingestion.pipeline import detect_mime_type
from services.ingestion.pipeline import run_ingestion_pipeline
from services.parser.pdf import _markdown_to_tree
from models.content import CourseContentTree


class _FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def execute(self, _stmt):
        class _Res:
            def scalar_one_or_none(self):
                return None

            def scalars(self):
                class _Scalars:
                    def all(self):
                        return []

                return _Scalars()

        return _Res()


def _assert_no_orphans(nodes):
    ids = {node.id for node in nodes}
    for node in nodes:
        if node.parent_id is not None:
            assert node.parent_id in ids


def test_markdown_tree_parent_ids_are_built_in_memory():
    course_id = uuid.uuid4()
    markdown = "# Chapter\nintro\n## Section\nbody\n### Topic\ndetails"

    nodes = _markdown_to_tree(markdown, course_id, "sample.pdf")

    assert len(nodes) >= 2
    _assert_no_orphans(nodes)


def test_markdown_tree_thinning_keeps_tree_consistent():
    course_id = uuid.uuid4()
    # Small content forces thinning on nested nodes.
    markdown = "# A\nx\n## B\ny\n### C\nz"

    nodes = _markdown_to_tree(markdown, course_id, "sample.pdf")

    assert len(nodes) >= 1
    _assert_no_orphans(nodes)


def test_markdown_tree_no_heading_fallback_keeps_parent_links():
    course_id = uuid.uuid4()
    markdown = "para1\n\npara2\n\npara3"

    nodes = _markdown_to_tree(markdown, course_id, "sample.pdf")

    assert len(nodes) >= 1
    _assert_no_orphans(nodes)


def test_detect_mime_type_fallback_on_detector_errors():
    class _BadFiletype:
        @staticmethod
        def guess(_data):
            raise RuntimeError("boom")

    class _BadMagic:
        @staticmethod
        def from_buffer(_data, mime=True):
            raise RuntimeError("boom")

    with patch.dict("sys.modules", {"filetype": _BadFiletype, "magic": _BadMagic}):
        assert detect_mime_type("doc.pdf", b"%PDF-1.7 content") == "application/pdf"


def test_crawl_result_to_extraction_handles_missing_markdown():
    class _Result:
        markdown = None

    extraction = _crawl_result_to_extraction(_Result(), "https://example.com")
    assert extraction.title == "https://example.com"
    assert extraction.content == ""


@pytest.mark.parametrize("query", [None, "calculus"])
def test_installed_crawler_generates_markdown_with_application_config(query):
    pytest.importorskip("crawl4ai")
    from services.ingestion.document_loader_extractors import _build_crawl4ai_config

    config = _build_crawl4ai_config(query)
    result = config.markdown_generator.generate_markdown(
        "<h1>Calculus</h1><p>Derivatives describe rates of change.</p>",
    )

    assert "Calculus" in result.raw_markdown
    assert "Derivatives describe rates of change." in result.raw_markdown
    if query:
        assert config.markdown_generator.content_filter.user_query == query


@pytest.fixture
def unavailable_crawler(monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    crawler = AsyncMock()
    crawler.__aenter__.side_effect = playwright.Error("Browser executable is missing")
    monkeypatch.setitem(sys.modules, "crawl4ai", SimpleNamespace(
        AsyncWebCrawler=lambda: crawler,
        CrawlerRunConfig=lambda **kwargs: None,
    ))
    monkeypatch.setattr("services.ingestion.document_loader._build_crawl4ai_config", lambda query: None)


@pytest.mark.asyncio
async def test_local_html_uses_fallback_when_browser_is_unavailable(unavailable_crawler, tmp_path):
    from services.ingestion.document_loader_formats import _extract_local_with_crawl4ai

    path = tmp_path / "lesson.html"
    path.write_text("<html><head><title>Calculus lesson</title></head><body><h1>Calculus lesson</h1><p>Derivatives describe rates of change.</p></body></html>")
    title, text = await _extract_local_with_crawl4ai(str(path))

    assert title == "lesson"
    assert "Derivatives describe rates of change." in text


@pytest.mark.asyncio
async def test_url_extraction_uses_fallback_when_browser_is_unavailable(unavailable_crawler):
    from services.ingestion.document_loader import extract_content_batch, extract_content_rich
    from services.ingestion.document_loader_extractors import _try_crawl4ai_url

    assert await _try_crawl4ai_url("https://example.com/lesson") is None
    with patch("services.ingestion.document_loader._extract_from_url", new=AsyncMock(return_value=("Lesson", "Material"))):
        result = await extract_content_rich("https://example.com/lesson")
        results = await extract_content_batch(["https://example.com/lesson"])

    assert result.title == "Lesson"
    assert result.content == "Material"
    assert len(results) == 1
    assert results[0].content == "Material"


@pytest.mark.asyncio
async def test_run_ingestion_pipeline_file_sets_source_fields():
    db = _FakeDB()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch(
        "services.ingestion.pipeline.extract_content_with_title",
        return_value=("Chapter 1", "# Chapter 1\nSection 1.1 overview with enough descriptive text to exceed fifty characters."),
    ):
        job = await run_ingestion_pipeline(
            db=db,
            user_id=user_id,
            file_path="/tmp/test.pdf",
            filename="lecture01.pdf",
            course_id=course_id,
            file_bytes=None,
        )

    nodes = [x for x in db.added if isinstance(x, CourseContentTree)]
    assert job.status == "embedding"
    assert job.progress_percent == 90
    assert job.embedding_status == "pending"
    assert job.nodes_created == len(nodes)
    assert nodes
    assert all(n.source_type == "file" for n in nodes)
    assert all(n.source_file == "lecture01.pdf" for n in nodes)


@pytest.mark.asyncio
async def test_run_ingestion_pipeline_url_sets_source_fields():
    db = _FakeDB()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    target_url = "https://example.com/lesson"

    with patch(
        "services.ingestion.pipeline.extract_content_with_title",
        return_value=(
            "Chapter 1",
            "# Chapter 1\n"
            "Section 1.1 overview with enough descriptive text to exceed fifty characters."
        ),
    ):
        job = await run_ingestion_pipeline(
            db=db,
            user_id=user_id,
            url=target_url,
            filename="",
            course_id=course_id,
            file_bytes=None,
        )

    nodes = [x for x in db.added if isinstance(x, CourseContentTree)]
    assert job.status == "embedding"
    assert job.progress_percent == 90
    assert job.embedding_status == "pending"
    assert job.nodes_created == len(nodes)
    assert nodes
    assert all(n.source_type == "url" for n in nodes)
    assert all(n.source_file == target_url for n in nodes)
    assert job.original_filename == "Chapter 1"


@pytest.mark.asyncio
async def test_run_ingestion_pipeline_preserves_original_error_when_setup_fails_early():
    db = _FakeDB()

    with patch(
        "services.ingestion.pipeline.detect_mime_type",
        side_effect=RuntimeError("mime detection broke"),
    ):
        job = await run_ingestion_pipeline(
            db=db,
            user_id=uuid.uuid4(),
            file_path="/tmp/test.pdf",
            filename="lecture01.pdf",
            course_id=uuid.uuid4(),
            file_bytes=b"%PDF-1.7 test",
        )

    assert job.status == "failed"
    assert job.error_message == "mime detection broke"
    assert getattr(job, "_canvas_file_urls", []) == []
    assert getattr(job, "_canvas_quiz_questions", []) == []
    assert getattr(job, "_canvas_assignments_data", []) == []
