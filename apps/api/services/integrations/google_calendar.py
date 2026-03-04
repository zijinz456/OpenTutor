"""Google Calendar OAuth2 and API service.

Handles the full OAuth2 flow (URL generation, code exchange, token refresh)
and provides helpers for syncing study plans and scanning for exam events.

All Google API library imports are guarded with try/except ImportError so the
rest of the application can start even when google-auth-oauthlib or
google-api-python-client are not installed.
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from config import settings

logger = logging.getLogger(__name__)

# Google OAuth2 configuration
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Keywords for exam scanning
EXAM_KEYWORDS = ["exam", "test", "quiz", "midterm", "final", "assessment", "evaluation"]


def _get_client_config() -> dict:
    """Return Google OAuth2 client configuration from settings."""
    client_id = getattr(settings, "google_client_id", "")
    client_secret = getattr(settings, "google_client_secret", "")
    redirect_uri = getattr(
        settings,
        "google_redirect_uri",
        "http://localhost:8000/api/integrations/google-calendar/callback",
    )

    if not client_id or not client_secret:
        raise ValueError(
            "Google Calendar integration requires GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET environment variables to be set."
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def _state_secret() -> bytes:
    secret = (
        getattr(settings, "jwt_secret_key", "")
        or getattr(settings, "google_client_secret", "")
        or "opentutor-google-calendar"
    )
    return secret.encode("utf-8")


def build_oauth_state(user_id: uuid.UUID) -> str:
    """Create a signed OAuth state value bound to a user."""
    payload = {
        "user_id": str(user_id),
        "issued_at": int(datetime.now(timezone.utc).timestamp()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_state_secret(), payload_bytes, hashlib.sha256).digest()
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    encoded_sig = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{encoded_payload}.{encoded_sig}"


def consume_oauth_state(state: str, max_age_seconds: int = 900) -> uuid.UUID:
    """Validate an OAuth state value and return the embedded user id."""
    try:
        encoded_payload, encoded_sig = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid OAuth state") from exc

    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}")

    def _canonical(value: str) -> str:
        return base64.urlsafe_b64encode(_decode(value)).decode("ascii").rstrip("=")

    # Reject non-canonical base64url encodings so single-character tampering
    # cannot slip through when it only mutates unused padding bits.
    if _canonical(encoded_payload) != encoded_payload or _canonical(encoded_sig) != encoded_sig:
        raise ValueError("Invalid OAuth state")

    payload_bytes = _decode(encoded_payload)
    expected_sig = hmac.new(_state_secret(), payload_bytes, hashlib.sha256).digest()
    actual_sig = _decode(encoded_sig)
    if not hmac.compare_digest(actual_sig, expected_sig):
        raise ValueError("Invalid OAuth state")

    payload = json.loads(payload_bytes.decode("utf-8"))
    issued_at = int(payload.get("issued_at", 0))
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if issued_at <= 0 or now_ts - issued_at > max_age_seconds:
        raise ValueError("OAuth state expired")

    try:
        return uuid.UUID(str(payload["user_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("Invalid OAuth state") from exc


def get_oauth_url(
    redirect_uri: str | None = None,
    *,
    state: str | None = None,
) -> str:
    """Build the Google OAuth2 authorization URL.

    Args:
        redirect_uri: Override the default redirect URI.

    Returns:
        The full authorization URL the user should visit.
    """
    config = _get_client_config()

    try:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "auth_uri": GOOGLE_AUTH_URI,
                    "token_uri": GOOGLE_TOKEN_URI,
                }
            },
            scopes=GOOGLE_CALENDAR_SCOPES,
        )
        flow.redirect_uri = redirect_uri or config["redirect_uri"]
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return authorization_url

    except ImportError:
        logger.info("google-auth-oauthlib not installed, building OAuth URL manually")
        params = {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri or config["redirect_uri"],
            "response_type": "code",
            "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{GOOGLE_AUTH_URI}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str | None = None) -> dict:
    """Exchange an authorization code for access and refresh tokens.

    Args:
        code: The authorization code from the OAuth2 callback.
        redirect_uri: Override the default redirect URI (must match the one used for auth).

    Returns:
        Dictionary with keys: access_token, refresh_token, expires_at, scopes.
    """
    config = _get_client_config()
    actual_redirect_uri = redirect_uri or config["redirect_uri"]

    try:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "auth_uri": GOOGLE_AUTH_URI,
                    "token_uri": GOOGLE_TOKEN_URI,
                }
            },
            scopes=GOOGLE_CALENDAR_SCOPES,
        )
        flow.redirect_uri = actual_redirect_uri
        flow.fetch_token(code=code)

        credentials = flow.credentials
        return {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_at": credentials.expiry.replace(tzinfo=timezone.utc) if credentials.expiry else None,
            "scopes": list(credentials.scopes) if credentials.scopes else GOOGLE_CALENDAR_SCOPES,
        }

    except ImportError:
        # Fallback: use httpx to exchange the code directly
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URI,
                data={
                    "code": code,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "redirect_uri": actual_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if response.status_code != 200:
                error_data = response.json()
                raise ValueError(
                    f"Token exchange failed: {error_data.get('error_description', error_data.get('error', 'unknown error'))}"
                )

            data = response.json()
            expires_in = data.get("expires_in", 3600)
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                "scopes": data.get("scope", "").split() or GOOGLE_CALENDAR_SCOPES,
            }


async def refresh_access_token(credential) -> str:
    """Refresh an expired access token using the refresh token.

    Args:
        credential: An IntegrationCredential instance with refresh_token set.

    Returns:
        The new access token string.

    Raises:
        ValueError: If no refresh token is available or refresh fails.
    """
    if not credential.refresh_token:
        raise ValueError("No refresh token available. User must re-authorize.")

    config = _get_client_config()

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=credential.access_token,
            refresh_token=credential.refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=config["client_id"],
            client_secret=config["client_secret"],
        )
        creds.refresh(Request())
        return creds.token

    except ImportError:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URI,
                data={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "refresh_token": credential.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code != 200:
                error_data = response.json()
                raise ValueError(
                    f"Token refresh failed: {error_data.get('error_description', error_data.get('error', 'unknown error'))}"
                )
            data = response.json()
            return data["access_token"]


def _build_calendar_service(credential):
    """Build a Google Calendar API service client.

    Args:
        credential: An IntegrationCredential instance.

    Returns:
        A googleapiclient.discovery.Resource for the Calendar API.

    Raises:
        ImportError: If google-api-python-client is not installed.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    config = _get_client_config()
    creds = Credentials(
        token=credential.access_token,
        refresh_token=credential.refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=config["client_id"],
        client_secret=config["client_secret"],
    )
    return build("calendar", "v3", credentials=creds)


async def sync_study_plan_to_calendar(
    credential,
    plan_events: list[dict[str, Any]],
) -> int:
    """Write study plan events to the user's Google Calendar.

    Args:
        credential: An IntegrationCredential instance with valid tokens.
        plan_events: List of event dicts, each with keys:
            - title (str): Event summary
            - start (str): ISO 8601 start datetime
            - end (str): ISO 8601 end datetime
            - description (str, optional): Event description

    Returns:
        Number of events successfully created.
    """
    try:
        service = _build_calendar_service(credential)
    except ImportError:
        raise ImportError(
            "google-api-python-client is required for calendar sync. "
            "Install it with: pip install google-api-python-client"
        )

    calendar_id = "primary"
    if credential.extra_data and credential.extra_data.get("calendar_id"):
        calendar_id = credential.extra_data["calendar_id"]

    created_count = 0
    for event_data in plan_events:
        event_body = {
            "summary": event_data.get("title", "Study Session"),
            "description": event_data.get("description", ""),
            "start": {
                "dateTime": event_data["start"],
                "timeZone": event_data.get("timezone", "UTC"),
            },
            "end": {
                "dateTime": event_data["end"],
                "timeZone": event_data.get("timezone", "UTC"),
            },
            "source": {
                "title": "OpenTutor",
                "url": "https://opentutor.dev",
            },
        }
        try:
            service.events().insert(calendarId=calendar_id, body=event_body).execute()
            created_count += 1
        except Exception as exc:
            logger.warning("Failed to create calendar event '%s': %s", event_data.get("title"), exc)

    logger.info("Synced %d/%d study events to Google Calendar", created_count, len(plan_events))
    return created_count


async def scan_for_exams(credential, days: int = 30) -> list[dict]:
    """Read calendar events and filter for exam/test/quiz keywords.

    Args:
        credential: An IntegrationCredential instance with valid tokens.
        days: Number of days ahead to scan (default 30).

    Returns:
        List of dicts with keys: id, title, start, end, description.
    """
    try:
        service = _build_calendar_service(credential)
    except ImportError:
        raise ImportError(
            "google-api-python-client is required for calendar scanning. "
            "Install it with: pip install google-api-python-client"
        )

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days)).isoformat()

    calendar_id = "primary"
    if credential.extra_data and credential.extra_data.get("calendar_id"):
        calendar_id = credential.extra_data["calendar_id"]

    try:
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch calendar events: %s", exc)
        raise ValueError(f"Failed to fetch calendar events: {exc}")

    exam_events = []
    for event in events_result.get("items", []):
        summary = (event.get("summary") or "").lower()
        description = (event.get("description") or "").lower()
        combined_text = f"{summary} {description}"

        if any(keyword in combined_text for keyword in EXAM_KEYWORDS):
            start = event.get("start", {})
            end = event.get("end", {})
            exam_events.append({
                "id": event.get("id"),
                "title": event.get("summary", ""),
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "description": event.get("description", ""),
            })

    logger.info("Found %d exam-related events in the next %d days", len(exam_events), days)
    return exam_events
