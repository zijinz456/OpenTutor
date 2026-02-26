"""File upload and URL scraping endpoints."""

import os
import uuid
import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.course import Course
from models.content import CourseContentTree
from services.parser.pdf import parse_pdf_to_tree
from services.parser.url import scrape_url_to_tree

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF file → parse with Marker → build content tree."""
    cid = uuid.UUID(course_id)

    # Verify course exists
    result = await db.execute(select(Course).where(Course.id == cid))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported in MVP")

    # Save file to disk
    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    save_path = os.path.join(settings.upload_dir, f"{file_hash}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    # Parse PDF → content tree nodes
    try:
        nodes = await parse_pdf_to_tree(save_path, cid, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF parsing failed: {e}")

    # Insert content tree nodes
    for node in nodes:
        db.add(node)
    await db.commit()

    return {
        "status": "ok",
        "file": file.filename,
        "nodes_created": len(nodes),
        "course_id": str(cid),
    }


@router.post("/url")
async def scrape_url(
    url: str = Form(...),
    course_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Scrape a URL → extract content → build content tree."""
    cid = uuid.UUID(course_id)

    result = await db.execute(select(Course).where(Course.id == cid))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        nodes = await scrape_url_to_tree(url, cid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"URL scraping failed: {e}")

    for node in nodes:
        db.add(node)
    await db.commit()

    return {
        "status": "ok",
        "url": url,
        "nodes_created": len(nodes),
        "course_id": str(cid),
    }
