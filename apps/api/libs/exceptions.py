"""Unified exception hierarchy for consistent API error responses.

Usage in routers / services:

    from libs.exceptions import NotFoundError, ConflictError, ValidationError

    raise NotFoundError("Goal", goal_id)
    raise ConflictError("Task is already completed")
    raise ValidationError("title must not be empty")

All AppError subclasses are caught by the global handler registered in main.py
and returned as ``{"code": "...", "message": "...", "status": <int>}``.
"""

from __future__ import annotations

import uuid


class AppError(Exception):
    """Base application error — all domain exceptions inherit from this."""

    code: str = "internal_error"
    status: int = 500

    def __init__(self, message: str = "Internal server error"):
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "status": self.status}


class NotFoundError(AppError):
    code = "not_found"
    status = 404

    def __init__(self, resource: str = "Resource", resource_id: uuid.UUID | str | None = None):
        detail = f"{resource} not found"
        if resource_id is not None:
            detail = f"{resource} {resource_id} not found"
        super().__init__(detail)


class ConflictError(AppError):
    code = "conflict"
    status = 409

    def __init__(self, message: str = "Conflict"):
        super().__init__(message)


class ValidationError(AppError):
    code = "validation_error"
    status = 422

    def __init__(self, message: str = "Validation error"):
        super().__init__(message)


class LLMUnavailableError(AppError):
    code = "llm_unavailable"
    status = 503

    def __init__(self, message: str = "LLM service is unavailable"):
        super().__init__(message)


class KnowledgeGraphUnavailableError(AppError):
    code = "knowledge_graph_unavailable"
    status = 500

    def __init__(self, message: str = "Knowledge graph service is unavailable"):
        super().__init__(message)


_LLM_UNAVAILABLE_PATTERNS = (
    "All LLM providers are unhealthy",
    "No LLM provider is configured",
    "No LLM API key configured",
)


def is_llm_unavailable_error(exc: BaseException) -> bool:
    message = str(exc)
    return any(pattern in message for pattern in _LLM_UNAVAILABLE_PATTERNS)


def reraise_as_app_error(exc: Exception, message: str) -> None:
    """Re-raise an exception as an AppError, detecting LLM unavailability."""
    if isinstance(exc, AppError):
        raise
    if is_llm_unavailable_error(exc):
        raise LLMUnavailableError(str(exc)) from exc
    raise AppError(message) from exc


class AuthenticationError(AppError):
    """Raised when authentication fails (missing/invalid/expired token)."""
    code = "authentication_error"
    status = 401

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)


class PermissionDeniedError(AppError):
    code = "permission_denied"
    status = 403

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message)


class IngestionError(AppError):
    """Raised when document ingestion or parsing fails."""
    code = "ingestion_error"
    status = 500

    def __init__(self, message: str = "Ingestion failed", source: str | None = None):
        self.source = source
        detail = f"Ingestion failed for {source}: {message}" if source else message
        super().__init__(detail)


class ToolExecutionError(AppError):
    """Raised when an agent tool fails during execution."""
    code = "tool_execution_error"
    status = 500

    def __init__(self, tool_name: str, message: str = "Tool execution failed"):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {message}")


class ContextBuildError(AppError):
    """Raised when context assembly for the agent fails."""
    code = "context_build_error"
    status = 500

    def __init__(self, phase: str = "unknown", message: str = "Context building failed"):
        self.phase = phase
        super().__init__(f"Context build error ({phase}): {message}")


class ExternalServiceError(AppError):
    """Raised when an external service (LLM, Canvas, embedding, etc.) fails."""
    code = "external_service_error"
    status = 502

    def __init__(self, service: str, message: str = "External service unavailable"):
        self.service = service
        super().__init__(f"{service}: {message}")


class ServiceTimeoutError(AppError):
    """Raised when an external service call times out."""
    code = "timeout_error"
    status = 504

    def __init__(self, service: str, timeout_seconds: float | None = None):
        self.service = service
        self.timeout_seconds = timeout_seconds
        detail = f"{service} timed out"
        if timeout_seconds is not None:
            detail += f" after {timeout_seconds}s"
        super().__init__(detail)


class ConfigurationError(AppError):
    """Raised when required configuration is missing or invalid at runtime."""
    code = "configuration_error"
    status = 500

    def __init__(self, message: str = "Configuration error"):
        super().__init__(message)


class RateLimitError(AppError):
    """Raised when a rate limit is exceeded."""
    code = "rate_limit_exceeded"
    status = 429

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message)
