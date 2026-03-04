"""OpenTutor CLI — one-command local startup.

Usage:
    opentutor              # Start on default port 8000
    opentutor --port 9000  # Custom port
    opentutor --host 0.0.0.0  # Listen on all interfaces
"""

import argparse
import os
import sys
from pathlib import Path


def _ensure_data_dir() -> Path:
    """Create ~/.opentutor/ if it doesn't exist and return the path."""
    data_dir = Path.home() / ".opentutor"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def main():
    parser = argparse.ArgumentParser(
        prog="opentutor",
        description="OpenTutor Zenus — your local AI learning assistant",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    data_dir = _ensure_data_dir()

    # Default DATABASE_URL to SQLite in ~/.opentutor/ if not set
    if not os.environ.get("DATABASE_URL"):
        db_path = data_dir / "data.db"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    # Default upload dir to ~/.opentutor/uploads/
    if not os.environ.get("UPLOAD_DIR"):
        upload_dir = data_dir / "uploads"
        upload_dir.mkdir(exist_ok=True)
        os.environ["UPLOAD_DIR"] = str(upload_dir)

    # Ensure the API source is on the Python path
    api_dir = Path(__file__).resolve().parent
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))

    import uvicorn

    print(f"\n  OpenTutor Zenus — Local AI Learning Assistant")
    print(f"  Database: {os.environ.get('DATABASE_URL', 'sqlite (default)')}")
    print(f"  Server:   http://{args.host}:{args.port}")
    print(f"  Data dir: {data_dir}\n")

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
