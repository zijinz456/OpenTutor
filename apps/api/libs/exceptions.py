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


class PermissionDeniedError(AppError):
    code = "permission_denied"
    status = 403

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message)
