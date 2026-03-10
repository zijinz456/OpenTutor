"""Tests for the unified exception hierarchy."""

import uuid
import pytest

from libs.exceptions import (
    AppError,
    NotFoundError,
    ConflictError,
    ValidationError,
    LLMUnavailableError,
    PermissionDeniedError,
    IngestionError,
    ToolExecutionError,
    ContextBuildError,
    ExternalServiceError,
    ServiceTimeoutError,
    ConfigurationError,
    RateLimitError,
    is_llm_unavailable_error,
    reraise_as_app_error,
)


class TestAppError:
    def test_default_message(self):
        e = AppError()
        assert e.message == "Internal server error"
        assert e.code == "internal_error"
        assert e.status == 500

    def test_custom_message(self):
        e = AppError("oops")
        assert e.message == "oops"

    def test_to_dict(self):
        e = AppError("test")
        d = e.to_dict()
        assert d == {"code": "internal_error", "message": "test", "status": 500}


class TestNotFoundError:
    def test_without_id(self):
        e = NotFoundError("Course")
        assert "Course not found" in e.message
        assert e.status == 404

    def test_with_uuid(self):
        uid = uuid.uuid4()
        e = NotFoundError("Course", uid)
        assert str(uid) in e.message

    def test_with_string_id(self):
        e = NotFoundError("Course", "abc-123")
        assert "abc-123" in e.message


class TestOtherErrors:
    def test_conflict(self):
        e = ConflictError("duplicate")
        assert e.status == 409

    def test_validation(self):
        e = ValidationError("bad input")
        assert e.status == 422

    def test_llm_unavailable(self):
        e = LLMUnavailableError()
        assert e.status == 503

    def test_permission_denied(self):
        e = PermissionDeniedError()
        assert e.status == 403

    def test_ingestion_with_source(self):
        e = IngestionError("parse failed", source="test.pdf")
        assert "test.pdf" in e.message
        assert e.source == "test.pdf"

    def test_ingestion_without_source(self):
        e = IngestionError("parse failed")
        assert e.source is None

    def test_tool_execution(self):
        e = ToolExecutionError("web_search", "timeout")
        assert "web_search" in e.message
        assert e.tool_name == "web_search"

    def test_context_build(self):
        e = ContextBuildError("rag", "index missing")
        assert "rag" in e.message
        assert e.phase == "rag"

    def test_external_service(self):
        e = ExternalServiceError("OpenAI", "rate limited")
        assert "OpenAI" in e.message
        assert e.status == 502

    def test_service_timeout_with_seconds(self):
        e = ServiceTimeoutError("Claude", timeout_seconds=30.0)
        assert "30.0s" in e.message
        assert e.status == 504

    def test_service_timeout_without_seconds(self):
        e = ServiceTimeoutError("Claude")
        assert "timed out" in e.message

    def test_configuration(self):
        e = ConfigurationError("missing key")
        assert e.status == 500

    def test_rate_limit(self):
        e = RateLimitError()
        assert e.status == 429


class TestIsLlmUnavailableError:
    def test_matching_pattern(self):
        assert is_llm_unavailable_error(Exception("All LLM providers are unhealthy"))
        assert is_llm_unavailable_error(Exception("No LLM provider is configured"))
        assert is_llm_unavailable_error(Exception("No LLM API key configured"))

    def test_non_matching(self):
        assert not is_llm_unavailable_error(Exception("random error"))


class TestReraiseAsAppError:
    def test_app_error_reraised_directly(self):
        """reraise_as_app_error uses bare 'raise' — must be called inside except block."""
        with pytest.raises(NotFoundError):
            try:
                raise NotFoundError("X")
            except Exception as e:
                reraise_as_app_error(e, "fallback")

    def test_llm_unavailable_detected(self):
        with pytest.raises(LLMUnavailableError):
            try:
                raise RuntimeError("All LLM providers are unhealthy")
            except Exception as e:
                reraise_as_app_error(e, "fallback")

    def test_generic_becomes_app_error(self):
        with pytest.raises(AppError, match="fallback"):
            try:
                raise ValueError("something")
            except Exception as e:
                reraise_as_app_error(e, "fallback")
