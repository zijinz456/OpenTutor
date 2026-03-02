"""Workspace file management endpoints.

Provides REST access to the user's sandboxed workspace directory for
browsing, downloading, and deleting files created by the agent.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Response
from fastapi.responses import FileResponse

from services.auth.dependency import get_current_user

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/files")
async def list_files(
    user=Depends(get_current_user),
):
    """List all files in the user's workspace."""
    from config import settings
    from services.filesystem.sandbox import get_user_workspace, list_workspace_files

    workspace = get_user_workspace(settings.upload_dir, user.id)
    return {"files": list_workspace_files(workspace)}


@router.get("/files/{filename:path}")
async def download_file(
    filename: str = PathParam(..., description="Filename to download"),
    user=Depends(get_current_user),
):
    """Download a file from the user's workspace."""
    from config import settings
    from services.filesystem.sandbox import get_user_workspace, validate_path

    workspace = get_user_workspace(settings.upload_dir, user.id)
    try:
        filepath = validate_path(workspace, filename)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
    )


@router.delete("/files/{filename:path}")
async def delete_file(
    filename: str = PathParam(..., description="Filename to delete"),
    user=Depends(get_current_user),
):
    """Delete a file from the user's workspace."""
    from config import settings
    from services.filesystem.sandbox import get_user_workspace, validate_path

    workspace = get_user_workspace(settings.upload_dir, user.id)
    try:
        filepath = validate_path(workspace, filename)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    os.unlink(filepath)
    return Response(status_code=204)
