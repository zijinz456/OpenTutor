"""Canvas file download logic.

Handles downloading files from Canvas LMS using authenticated sessions,
with URL normalization and binary content detection.

Extracted from canvas_loader.py.
"""

import asyncio
import logging
import re
from pathlib import Path

import httpx

from services.ingestion.canvas_http import _load_session_cookies

logger = logging.getLogger(__name__)


async def download_canvas_file(
    file_info: dict,
    session_name: str | None,
    target_domain: str | None,
    save_dir: str = "uploads",
) -> str | None:
    """Download a Canvas file and save to disk."""
    import os
    import hashlib

    url = file_info["url"]
    display_url = file_info.get("display_url", url)
    filename = file_info.get("filename", "file.pdf")
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)

    cookies = _load_session_cookies(session_name, target_domain=target_domain) if session_name else {}

    def _ensure_download_url(u: str) -> str:
        clean = u.split("?")[0].rstrip("/")
        if clean.endswith("/download"):
            return clean
        if re.search(r"/files/\d+$", clean):
            return f"{clean}/download"
        return clean

    def _is_binary_content(resp) -> bool:
        ct = resp.headers.get("content-type", "")
        if "text/html" in ct:
            return False
        if any(t in ct for t in ("application/pdf", "application/octet", "application/vnd", "application/zip")):
            return True
        if resp.content[:4] == b"%PDF":
            return True
        if resp.content[:2] == b"PK":
            return True
        return len(resp.content) > 1000 and b"<html" not in resp.content[:500].lower()

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60, cookies=cookies) as client:
            candidates = []
            candidates.append(_ensure_download_url(url))
            if display_url and display_url != url:
                candidates.append(_ensure_download_url(display_url))
            seen = set()
            unique_candidates = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique_candidates.append(c)

            for try_url in unique_candidates:
                try:
                    resp = await client.get(try_url)
                    if resp.status_code == 200 and _is_binary_content(resp) and len(resp.content) > 100:
                        os.makedirs(save_dir, exist_ok=True)
                        file_hash = hashlib.sha256(resp.content).hexdigest()[:12]
                        save_path = os.path.join(save_dir, f"{file_hash}_{filename}")
                        await asyncio.to_thread(Path(save_path).write_bytes, resp.content)
                        logger.info("Downloaded Canvas file: %s (%d bytes)", filename, len(resp.content))
                        return save_path
                except (httpx.HTTPError, OSError) as e:
                    logger.warning("Canvas download attempt failed for %s: %s", try_url, e)

            logger.warning("All download attempts failed for: %s", filename)
    except (httpx.HTTPError, OSError) as e:
        logger.exception("Canvas file download error for %s", filename)

    return None
