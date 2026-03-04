"""Integration credential model for storing OAuth2 tokens for external services."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, func, UniqueConstraint
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class IntegrationCredential(Base):
    """Stores OAuth2 credentials for external service integrations.

    Each row represents a user's connection to an external service (e.g.
    Google Calendar, Notion). Tokens are encrypted at rest via Fernet when
    ENCRYPTION_KEY is configured.
    """

    __tablename__ = "integration_credentials"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    integration_name: Mapped[str] = mapped_column(String(50))  # e.g. "google_calendar", "notion"
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True)  # list of OAuth scopes granted
    extra_data: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)  # e.g. {"calendar_id": "primary"}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "integration_name", name="uq_user_integration"),
    )

    def set_access_token(self, plaintext: str) -> None:
        """Encrypt and store the access token."""
        from libs.encryption import encrypt_value
        self.access_token = encrypt_value(plaintext)

    def get_access_token(self) -> str:
        """Decrypt and return the access token."""
        from libs.encryption import decrypt_value
        return decrypt_value(self.access_token)

    def set_refresh_token(self, plaintext: str | None) -> None:
        """Encrypt and store the refresh token."""
        if plaintext is None:
            self.refresh_token = None
            return
        from libs.encryption import encrypt_value
        self.refresh_token = encrypt_value(plaintext)

    def get_refresh_token(self) -> str | None:
        """Decrypt and return the refresh token."""
        if self.refresh_token is None:
            return None
        from libs.encryption import decrypt_value
        return decrypt_value(self.refresh_token)
