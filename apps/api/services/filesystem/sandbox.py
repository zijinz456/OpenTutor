"""Sandboxed filesystem operations for agent workspace.

All file operations are restricted to a per-user workspace directory under
the configured upload_dir. Path traversal, symlink, and size attacks are
prevented at the validation layer.
"""

import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file
MAX_WORKSPACE_FILES = 1000
ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".html"}


def get_user_workspace(upload_dir: str, user_id: uuid.UUID) -> Path:
    """Get (and create) the workspace directory for a user."""
    workspace = Path(upload_dir).resolve() / str(user_id) / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def validate_path(base_dir: Path, requested: str) -> Path:
    """Validate and resolve a requested path within the sandbox.

    Raises PermissionError for path traversal, symlinks, or disallowed extensions.
    """
    # Reject absolute paths
    if os.path.isabs(requested):
        raise PermissionError(f"Absolute paths are not allowed: {requested}")

    # Reject path traversal components
    if ".." in Path(requested).parts:
        raise PermissionError(f"Path traversal not allowed: {requested}")

    # Reject symlinks BEFORE resolve to prevent TOCTOU race
    raw_path = base_dir / requested
    if raw_path.exists() and raw_path.is_symlink():
        raise PermissionError(f"Symlinks are not allowed: {requested}")

    resolved = raw_path.resolve()

    # Ensure the resolved path is within the sandbox
    if not resolved.is_relative_to(base_dir):
        raise PermissionError(f"Path escapes sandbox: {requested}")

    # Check extension whitelist (reject files without extensions too)
    ext = resolved.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise PermissionError(
            f"File extension '{ext or '(none)'}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    return resolved


def _check_workspace_limits_sync(workspace: Path, new_content_size: int = 0) -> None:
    """Synchronous implementation — call via asyncio.to_thread from async code."""
    from config import settings

    max_size_bytes = settings.workspace_max_size_mb * 1024 * 1024

    file_count = 0
    total_size = 0
    for f in workspace.rglob("*"):
        if f.is_file():
            file_count += 1
            total_size += f.stat().st_size

    if file_count >= MAX_WORKSPACE_FILES:
        raise ValueError(
            f"Workspace file limit reached ({MAX_WORKSPACE_FILES} files). "
            "Delete some files before creating new ones."
        )

    if new_content_size > MAX_FILE_SIZE:
        raise ValueError(
            f"File too large ({new_content_size / 1024 / 1024:.1f} MB). "
            f"Maximum file size is {MAX_FILE_SIZE / 1024 / 1024:.0f} MB."
        )

    if total_size + new_content_size > max_size_bytes:
        raise ValueError(
            f"Workspace size limit would be exceeded "
            f"({(total_size + new_content_size) / 1024 / 1024:.1f} MB / "
            f"{settings.workspace_max_size_mb} MB)."
        )


async def check_workspace_limits(workspace: Path, new_content_size: int = 0) -> None:
    """Check that the workspace doesn't exceed file count or size limits.

    Runs the blocking rglob traversal in a thread to avoid blocking the event loop.
    """
    import asyncio
    await asyncio.to_thread(_check_workspace_limits_sync, workspace, new_content_size)


def _list_workspace_files_sync(workspace: Path) -> list[dict]:
    """Synchronous implementation — call via asyncio.to_thread from async code."""
    files = []
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            stat = f.stat()
            files.append({
                "name": str(f.relative_to(workspace)),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
    return files


async def list_workspace_files(workspace: Path) -> list[dict]:
    """List all files in the workspace with metadata.

    Runs the blocking rglob traversal in a thread to avoid blocking the event loop.
    """
    import asyncio
    return await asyncio.to_thread(_list_workspace_files_sync, workspace)
