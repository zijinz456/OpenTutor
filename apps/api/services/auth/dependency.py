"""FastAPI dependency for user authentication.

When AUTH_ENABLED=false (default), falls back to single-user local mode.
When AUTH_ENABLED=true, requires a valid JWT bearer token.
"""

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.user import User

security = HTTPBearer(auto_error=False)
SCHEMA_INIT_DETAIL = "Database schema is not initialized. Run 'alembic upgrade head' before starting the API."


def _is_missing_user_table(exc: ProgrammingError) -> bool:
    message = str(exc).lower()
    return 'relation "users" does not exist' in message or "no such table: users" in message


async def _execute_user_query(db: AsyncSession, query):
    try:
        return await db.execute(query)
    except ProgrammingError as exc:
        if _is_missing_user_table(exc):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=SCHEMA_INIT_DETAIL,
            ) from exc
        raise


async def get_current_user(
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    """Resolve the current user from JWT or fall back to local user."""
    if settings.deployment_mode == "single_user" and not settings.auth_enabled:
        # Explicit single-user deployment mode.
        result = await _execute_user_query(db, select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            user = User(name="Owner")
            db.add(user)
            await db.commit()
            await db.refresh(user)
        if request is not None:
            request.state.user_id = str(user.id)
            request.state.deployment_mode = settings.deployment_mode
        return user

    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_ENABLED must be true when DEPLOYMENT_MODE is multi_user",
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from services.auth.jwt import decode_token
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = uuid.UUID(payload["sub"])
    except HTTPException:
        raise  # Re-raise specific HTTP errors (e.g. "Invalid token type") as-is
    except (ValueError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    result = await _execute_user_query(db, select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if request is not None:
        request.state.user_id = str(user.id)
        request.state.deployment_mode = settings.deployment_mode
    return user
