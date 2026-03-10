"""Persistent session manager using Playwright storageState.

Each session is stored as a JSON file: ./sessions/{session_name}_state.json
storageState captures cookies + localStorage (richer than just cookies).

Features:
- Health check: load page and check for auth indicators (HTTP status, redirect, CSS selectors)
- Re-authentication: replay login_actions with {ENV:VAR_NAME} placeholder resolution
- Backward compatible: falls back to loading legacy _cookies.json files

Reference: Playwright docs — https://playwright.dev/python/docs/auth
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_DIR = Path("./sessions")
SESSION_DIR.mkdir(exist_ok=True)

# Pattern for environment variable placeholders: {ENV:VAR_NAME}
_ENV_PATTERN = re.compile(r"\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}")
_SESSION_NAME_SANITIZER = re.compile(r"[^A-Za-z0-9_-]+")


def _resolve_env_placeholders(value: str) -> str:
    """Replace {ENV:VAR_NAME} placeholders with actual environment variable values."""

    def _replace(match):
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            logger.warning("Environment variable %s not set for session action", var_name)
            return match.group(0)  # leave placeholder unchanged
        return env_val

    return _ENV_PATTERN.sub(_replace, value)


def _resolve_actions(actions: list[dict]) -> list[dict]:
    """Deep-resolve {ENV:VAR_NAME} placeholders in action values."""
    resolved = []
    for action in actions:
        new_action = {}
        for key, val in action.items():
            if isinstance(val, str):
                new_action[key] = _resolve_env_placeholders(val)
            else:
                new_action[key] = val
        resolved.append(new_action)
    return resolved


def _get_fernet():
    """Get Fernet cipher from encryption_key config. Returns None if unavailable."""
    try:
        from config import settings
        if settings.encryption_key:
            from cryptography.fernet import Fernet
            return Fernet(settings.encryption_key.encode() if isinstance(settings.encryption_key, str) else settings.encryption_key)
    except (ImportError, ValueError, TypeError) as e:
        logger.debug("Fernet encryption unavailable: %s", e)
    return None


def _encrypt_data(data: str) -> str:
    """Encrypt JSON string if encryption key is configured."""
    fernet = _get_fernet()
    if fernet:
        return fernet.encrypt(data.encode()).decode()
    return data


def _decrypt_data(data: str) -> str:
    """Decrypt data if encrypted, otherwise return as-is (backward compat)."""
    fernet = _get_fernet()
    if fernet:
        try:
            return fernet.decrypt(data.encode()).decode()
        except (ValueError, TypeError):
            # Data is not encrypted (legacy file) — return as-is
            return data
    return data


class SessionManager:
    """Manages Playwright browser sessions with storageState persistence."""

    @staticmethod
    def normalize_session_name(session_name: str) -> str:
        """Normalize session names to filesystem-safe tokens."""
        normalized = _SESSION_NAME_SANITIZER.sub("_", session_name).strip("_")
        return normalized or "default"

    @staticmethod
    def state_file(session_name: str) -> Path:
        normalized = SessionManager.normalize_session_name(session_name)
        return SESSION_DIR / f"{normalized}_state.json"

    @staticmethod
    def _legacy_cookie_file(session_name: str) -> Path:
        """Legacy cookie file path for backward compatibility."""
        normalized = SessionManager.normalize_session_name(session_name)
        return SESSION_DIR / f"{normalized}_cookies.json"

    @staticmethod
    async def save_state(context, session_name: str) -> Path:
        """Save browser context state (cookies + localStorage) to disk.

        Encrypts with Fernet if ENCRYPTION_KEY is configured.
        """
        path = SessionManager.state_file(session_name)
        state = await context.storage_state()
        raw_json = json.dumps(state, indent=2)
        path.write_text(_encrypt_data(raw_json))
        # Restrict file permissions to owner-only (rwx------)
        path.chmod(0o600)
        logger.info("Session state saved: %s (encrypted=%s)", session_name, _get_fernet() is not None)
        return path

    @staticmethod
    def _load_state_json(path: Path) -> dict:
        """Load and decrypt a state file."""
        raw = path.read_text()
        decrypted = _decrypt_data(raw)
        return json.loads(decrypted)

    @staticmethod
    async def create_context_with_state(browser, session_name: str):
        """Create a Playwright browser context with saved state.

        Falls back to loading legacy _cookies.json if no _state.json exists.
        Decrypts state files automatically if encrypted.
        """
        state_path = SessionManager.state_file(session_name)
        legacy_path = SessionManager._legacy_cookie_file(session_name)

        if state_path.exists():
            state = SessionManager._load_state_json(state_path)
            context = await browser.new_context(storage_state=state)
            logger.info("Loaded session state: %s", session_name)
            return context

        if legacy_path.exists():
            # Backward compat: load old cookie-only files
            cookies = json.loads(legacy_path.read_text())
            context = await browser.new_context()
            await context.add_cookies(cookies)
            logger.info("Loaded legacy cookies for %s, will upgrade to storageState", session_name)
            # Save as full storageState for future runs (now encrypted)
            await SessionManager.save_state(context, session_name)
            return context

        context = await browser.new_context()
        logger.info("No saved state for %s, created fresh context", session_name)
        return context

    @staticmethod
    async def validate_session(
        browser,
        session_name: str,
        check_url: str,
        success_selector: str | None = None,
        failure_selector: str | None = None,
    ) -> bool:
        """Check if a saved session is still valid.

        Uses 3-signal detection:
        1. HTTP status code (401/403 = expired)
        2. Redirect to login page
        3. Optional CSS selector checks
        """
        state_path = SessionManager.state_file(session_name)
        if not state_path.exists():
            return False

        try:
            context = await SessionManager.create_context_with_state(browser, session_name)
            page = await context.new_page()
            response = await page.goto(check_url, wait_until="domcontentloaded", timeout=15000)

            is_valid = True

            # Signal 1: HTTP status
            if response and response.status in (401, 403):
                is_valid = False

            # Signal 2: Redirect to login page
            if response and is_valid:
                current_url = page.url.lower()
                original_url = check_url.lower()
                if "login" in current_url and "login" not in original_url:
                    is_valid = False

            # Signal 3: CSS selector checks
            if success_selector and is_valid:
                try:
                    await page.wait_for_selector(success_selector, timeout=3000)
                except (TimeoutError, OSError, RuntimeError):
                    is_valid = False

            if failure_selector:
                try:
                    await page.wait_for_selector(failure_selector, timeout=1000)
                    is_valid = False  # login form visible = not authenticated
                except (TimeoutError, OSError, RuntimeError):
                    pass  # failure indicator NOT found = good

            await context.close()
            return is_valid
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            logger.exception("Session validation failed for %s", session_name)
            return False

    @staticmethod
    async def re_authenticate(
        browser,
        session_name: str,
        login_url: str,
        actions: list[dict],
    ) -> bool:
        """Re-authenticate using stored login actions.

        Resolves {ENV:VAR_NAME} placeholders in action values from os.environ.
        Reuses the action format from automation.py (click, fill, wait, submit).
        Saves storageState on success.
        """
        resolved = _resolve_actions(actions)

        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(login_url, wait_until="networkidle", timeout=30000)

            for action in resolved:
                action_type = action.get("type")
                if action_type == "click":
                    await page.click(action["selector"])
                elif action_type == "fill":
                    await page.fill(action["selector"], action["value"])
                elif action_type == "wait":
                    await page.wait_for_selector(action["selector"], timeout=10000)
                elif action_type == "submit":
                    await page.click(action.get("selector", "button[type='submit']"))
                    await page.wait_for_load_state("networkidle")

            # Save updated state
            await SessionManager.save_state(context, session_name)
            await context.close()
            logger.info("Re-authentication succeeded for %s", session_name)
            return True
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            logger.exception("Re-authentication failed for %s", session_name)
            return False

    @staticmethod
    async def fetch_with_session(
        browser,
        session_name: str,
        url: str,
    ) -> str | None:
        """Fetch a URL using a saved session. Returns page HTML content."""
        try:
            context = await SessionManager.create_context_with_state(browser, session_name)
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            content = await page.content()

            # Update saved state (cookies may have been refreshed by the server)
            await SessionManager.save_state(context, session_name)
            await context.close()
            return content
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            logger.exception("Session fetch failed for %s", url)
            return None
