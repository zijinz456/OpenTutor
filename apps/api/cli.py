"""OpenTutor CLI — one-command local startup (OpenClaw-inspired pattern).

Usage:
    opentutor              # Start server on default port 8000
    opentutor start        # Same as above
    opentutor init         # Guided first-time setup (detect Ollama, pull model)
    opentutor --port 9000  # Custom port
    opentutor --no-browser # Don't auto-open browser
"""

import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _ensure_data_dir() -> Path:
    """Create ~/.opentutor/ if it doesn't exist and return the path."""
    data_dir = Path.home() / ".opentutor"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _detect_ollama() -> dict | None:
    """Probe local Ollama for available models."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            models = [line.split()[0] for line in lines[1:] if line.strip()]
            return {"models": models}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _cmd_init(_args):
    """Interactive first-time setup wizard."""
    data_dir = _ensure_data_dir()
    config_file = data_dir / "config.env"

    print("\n  OpenTutor Zenus — First-Time Setup\n")

    # 1. Detect Ollama
    print("  Checking for local LLM (Ollama)...")
    ollama = _detect_ollama()

    if ollama:
        models = ollama["models"]
        if models:
            print(f"  ✓ Ollama detected with {len(models)} model(s): {', '.join(models[:5])}")
        else:
            print("  ✓ Ollama is installed but has no models.")
            print("  Pulling llama3.2:3b (recommended starter model)...")
            try:
                subprocess.run(["ollama", "pull", "llama3.2:3b"], check=True)
                print("  ✓ Model pulled successfully.")
            except subprocess.CalledProcessError:
                print("  ✗ Failed to pull model. You can do it manually: ollama pull llama3.2:3b")
    else:
        print("  ✗ Ollama not found.")
        print()
        print("  To use a local LLM (recommended, free):")
        print("    1. Install Ollama: https://ollama.com")
        print("    2. Run: ollama pull llama3.2:3b")
        print()
        print("  Or use a cloud provider:")
        print("    export OPENAI_API_KEY=sk-...")
        print("    export LLM_PROVIDER=openai")
        print("    export LLM_MODEL=gpt-4o-mini")

    # 2. Write config if none exists
    if not config_file.exists():
        if ollama and ollama["models"]:
            # Use the first available model, prefer llama3.2:3b if present
            models = ollama["models"]
            model = "llama3.2:3b" if "llama3.2:3b" in models else models[0]
            config_lines = [
                "LLM_PROVIDER=ollama",
                f"LLM_MODEL={model}",
            ]
        elif ollama:
            # Ollama installed but no models yet
            config_lines = [
                "LLM_PROVIDER=ollama",
                "LLM_MODEL=llama3.2:3b",
            ]
        else:
            # No Ollama — leave blank so user configures manually
            config_lines = [
                "# LLM_PROVIDER=ollama",
                "# LLM_MODEL=llama3.2:3b",
                "# Uncomment above after installing Ollama, or set your cloud provider:",
                "# LLM_PROVIDER=openai",
                "# OPENAI_API_KEY=sk-...",
            ]
        config_file.write_text("\n".join(config_lines) + "\n")
        print(f"\n  Config saved to: {config_file}")
    else:
        print(f"\n  Config already exists: {config_file}")

    print(f"\n  Data directory: {data_dir}")
    print(f"  Database:       {data_dir / 'data.db'} (SQLite)")
    print()
    print("  Setup complete! Run 'opentutor' to start.\n")


def _auto_init_if_needed(data_dir: Path) -> None:
    """Auto-run first-time setup if no config exists (zero-friction start)."""
    config_file = data_dir / "config.env"
    if config_file.exists():
        return

    print("\n  First run detected — auto-configuring...\n")

    # Detect Ollama
    ollama = _detect_ollama()
    llm_status = ""

    if ollama:
        models = ollama["models"]
        if models:
            model = "llama3.2:3b" if "llama3.2:3b" in models else models[0]
            config_lines = [f"LLM_PROVIDER=ollama", f"LLM_MODEL={model}"]
            llm_status = f"  LLM:       Ollama ({model})"
        else:
            # Ollama installed, no models — try to pull one
            print("  Ollama found but no models. Pulling llama3.2:3b...")
            try:
                subprocess.run(
                    ["ollama", "pull", "llama3.2:3b"],
                    check=True,
                    timeout=300,
                )
                config_lines = ["LLM_PROVIDER=ollama", "LLM_MODEL=llama3.2:3b"]
                llm_status = "  LLM:       Ollama (llama3.2:3b)"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                config_lines = ["LLM_PROVIDER=ollama", "LLM_MODEL=llama3.2:3b"]
                llm_status = "  LLM:       Ollama (model pull failed — run: ollama pull llama3.2:3b)"
    else:
        # Check for cloud API keys in environment
        for provider, key_name in [
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("deepseek", "DEEPSEEK_API_KEY"),
        ]:
            if os.environ.get(key_name):
                config_lines = [f"LLM_PROVIDER={provider}"]
                llm_status = f"  LLM:       {provider} (from {key_name})"
                break
        else:
            # No LLM found — start anyway with mock fallback
            config_lines = [
                "# No LLM detected. Install Ollama (https://ollama.com) or set an API key.",
                "# LLM_PROVIDER=ollama",
                "# LLM_MODEL=llama3.2:3b",
            ]
            llm_status = "  LLM:       None (install Ollama: https://ollama.com)"

    config_file.write_text("\n".join(config_lines) + "\n")
    if llm_status:
        print(llm_status)
    print(f"  Config:    {config_file}")
    print()


def _cmd_start(args):
    """Start the OpenTutor server."""
    data_dir = _ensure_data_dir()

    # Auto-init on first run (no separate 'opentutor init' needed)
    _auto_init_if_needed(data_dir)

    # Default DATABASE_URL to SQLite in ~/.opentutor/ if not set
    if not os.environ.get("DATABASE_URL"):
        db_path = data_dir / "data.db"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    # Default upload dir to ~/.opentutor/uploads/
    if not os.environ.get("UPLOAD_DIR"):
        upload_dir = data_dir / "uploads"
        upload_dir.mkdir(exist_ok=True)
        os.environ["UPLOAD_DIR"] = str(upload_dir)

    # Load user config from ~/.opentutor/config.env if it exists
    config_file = data_dir / "config.env"
    if config_file.exists():
        for line in config_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    # Enable built-in web UI (no Node.js needed)
    os.environ.setdefault("SERVE_BUILTIN_UI", "true")

    # Ensure the API source is on the Python path
    api_dir = Path(__file__).resolve().parent
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))

    url = f"http://{args.host}:{args.port}"
    db_display = os.environ.get("DATABASE_URL", "sqlite (default)")
    if "sqlite" in db_display:
        db_display = f"SQLite ({data_dir / 'data.db'})"

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   OpenTutor Zenus — Your Learning Site    ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print(f"  Web UI:    {url}")
    print(f"  Database:  {db_display}")
    print(f"  Data dir:  {data_dir}")
    print()

    # Auto-open browser once server is ready (poll health endpoint)
    if not args.no_browser:
        def _open_browser():
            import urllib.request
            for _ in range(30):  # Wait up to 15s
                time.sleep(0.5)
                try:
                    urllib.request.urlopen(f"{url}/api/health", timeout=2)
                    break
                except Exception:
                    continue
            webbrowser.open(url)
        threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


def main():
    parser = argparse.ArgumentParser(
        prog="opentutor",
        description="OpenTutor Zenus — your local AI learning assistant",
    )
    subparsers = parser.add_subparsers(dest="command")

    # opentutor init
    subparsers.add_parser("init", help="First-time setup wizard (detect Ollama, configure)")

    # opentutor start (explicit)
    start_parser = subparsers.add_parser("start", help="Start the server")
    start_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    start_parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    start_parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    start_parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    # Also support `opentutor --port 8000` (no subcommand = start)
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")

    args = parser.parse_args()

    if args.command == "init":
        _cmd_init(args)
    else:
        _cmd_start(args)


if __name__ == "__main__":
    main()
