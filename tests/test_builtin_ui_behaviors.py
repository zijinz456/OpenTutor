"""Regression checks for built-in UI script behavior."""

from routers.ui import _INDEX_HTML


def test_builtin_ui_upload_uses_supported_endpoint_and_course_id():
    assert "API+'/content/upload'" in _INDEX_HTML
    assert "fd.append('course_id',currentCourse.id);" in _INDEX_HTML


def test_builtin_ui_upload_exposes_diagnostic_error_mapping():
    assert "res.status===401" in _INDEX_HTML
    assert "res.status===403" in _INDEX_HTML
    assert "res.status===404" in _INDEX_HTML
    assert "res.status===422" in _INDEX_HTML


def test_builtin_ui_markdown_links_use_scheme_whitelist():
    assert "function safeLink(url)" in _INDEX_HTML
    assert "protocol==='http:'||protocol==='https:'||protocol==='mailto:'" in _INDEX_HTML
    assert "const href=safeLink(url);" in _INDEX_HTML
