"""Sandboxed filesystem tools for agent workspace operations.

Provides write, read, and list capabilities within a per-user sandbox directory.
All paths are validated against traversal attacks and restricted to allowed extensions.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class WriteFileTool(Tool):
    """Write content to a file in the user's workspace."""

    name = "write_file"
    description = (
        "Write content to a file in the student's workspace. "
        "Useful for saving study notes, summaries, or exported data. "
        "Files are stored in a sandboxed directory per user."
    )
    domain = "file"
    category = ToolCategory.WRITE

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="filename",
                type="string",
                description="Filename to write (e.g. 'chapter1-notes.md'). Allowed extensions: .md, .txt, .json, .csv, .html",
                required=True,
            ),
            ToolParameter(
                name="content",
                type="string",
                description="The text content to write to the file.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from config import settings
        from services.filesystem.sandbox import (
            check_workspace_limits,
            get_user_workspace,
            validate_path,
        )

        try:
            filename = parameters.get("filename", "").strip()
            content = parameters.get("content", "")

            if not filename:
                return ToolResult(success=False, output="", error="Filename is required.")

            workspace = get_user_workspace(settings.upload_dir, ctx.user_id)
            filepath = validate_path(workspace, filename)
            await check_workspace_limits(workspace, len(content.encode("utf-8")))

            # Ensure parent directories exist (for paths like "chapter1/notes.md")
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")

            size_kb = filepath.stat().st_size / 1024
            return ToolResult(
                success=True,
                output=f"File saved: {filename} ({size_kb:.1f} KB)",
                metadata={"filename": filename, "size_bytes": filepath.stat().st_size},
            )
        except (PermissionError, ValueError) as e:
            return ToolResult(success=False, output="", error=str(e))
        except (IOError, OSError, RuntimeError) as e:
            logger.exception("write_file failed: %s", e)
            return ToolResult(success=False, output="", error=f"File write failed: {e}")


class ListFilesTool(Tool):
    """List files in the user's workspace."""

    name = "list_files"
    description = (
        "List all files in the student's workspace directory. "
        "Shows filenames, sizes, and modification times."
    )
    domain = "file"
    category = ToolCategory.READ

    def get_parameters(self) -> list[ToolParameter]:
        return []

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from config import settings
        from services.filesystem.sandbox import get_user_workspace, list_workspace_files

        try:
            workspace = get_user_workspace(settings.upload_dir, ctx.user_id)
            files = await list_workspace_files(workspace)

            if not files:
                return ToolResult(success=True, output="Workspace is empty. No files yet.")

            lines = [f"Workspace files ({len(files)}):\n"]
            for f in files:
                size_str = f"{f['size'] / 1024:.1f} KB" if f["size"] >= 1024 else f"{f['size']} B"
                lines.append(f"- {f['name']} ({size_str})")

            return ToolResult(success=True, output="\n".join(lines))
        except (IOError, OSError, RuntimeError) as e:
            logger.exception("list_files failed: %s", e)
            return ToolResult(success=False, output="", error=f"Failed to list files: {e}")


class ReadFileTool(Tool):
    """Read a file from the user's workspace."""

    name = "read_file"
    description = (
        "Read the contents of a file from the student's workspace. "
        "Use this to retrieve previously saved notes or exported data."
    )
    domain = "file"
    category = ToolCategory.READ

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="filename",
                type="string",
                description="Filename to read from the workspace.",
                required=True,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from config import settings
        from services.filesystem.sandbox import get_user_workspace, validate_path

        try:
            filename = parameters.get("filename", "").strip()
            if not filename:
                return ToolResult(success=False, output="", error="Filename is required.")

            workspace = get_user_workspace(settings.upload_dir, ctx.user_id)
            filepath = validate_path(workspace, filename)

            if not filepath.exists():
                return ToolResult(success=False, output="", error=f"File not found: {filename}")

            content = filepath.read_text(encoding="utf-8")
            return ToolResult(
                success=True,
                output=content,
                metadata={"filename": filename, "size_bytes": len(content.encode("utf-8"))},
            )
        except PermissionError as e:
            return ToolResult(success=False, output="", error=str(e))
        except (IOError, OSError, RuntimeError) as e:
            logger.exception("read_file failed: %s", e)
            return ToolResult(success=False, output="", error=f"File read failed: {e}")
