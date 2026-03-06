"""Application configuration via environment variables."""

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"

    # Database — defaults to SQLite at ~/.opentutor/data.db if DATABASE_URL not set
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    # LLM — primary provider selection
    llm_provider: str = "ollama"  # ollama | openai | anthropic | deepseek | openrouter | gemini | groq | vllm | lmstudio | textgenwebui | custom
    llm_model: str = "llama3.2:3b"

    # Cloud providers
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Local inference backends
    ollama_base_url: str = "http://localhost:11434"
    vllm_base_url: str = "http://localhost:8000/v1"
    lmstudio_base_url: str = "http://localhost:1234/v1"
    textgenwebui_base_url: str = "http://localhost:5000/v1"

    # Generic OpenAI-compatible endpoint
    custom_llm_api_key: str = ""
    custom_llm_base_url: str = ""
    custom_llm_model: str = ""

    # LiteLLM integration (opt-in alternative provider)
    use_litellm: bool = False
    litellm_model: str = ""  # Model string for LiteLLM (e.g., "openai/gpt-4o")
    litellm_api_base: str = ""  # Optional custom API base for LiteLLM proxy
    litellm_api_key: str = ""  # Optional API key for LiteLLM proxy

    # Model size routing (agent preference hints)
    llm_model_large: str = ""   # e.g. gpt-4o for teaching/planning agents
    llm_model_small: str = ""   # e.g. gpt-4o-mini for preference/scene agents
    llm_required: bool = False

    # 3-tier model routing (overrides large/small when set)
    llm_model_fast: str = ""       # e.g. gpt-4o-mini — greetings, preferences
    llm_model_standard: str = ""   # e.g. gpt-4o — teaching, exercises
    llm_model_frontier: str = ""   # e.g. o3-mini — planning, code execution

    # Authentication
    auth_enabled: bool = False
    deployment_mode: str = "single_user"  # single_user | multi_user
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    # File Upload
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50
    scrape_fixture_dir: str = ""

    # Runtime bootstrap
    app_auto_create_tables: bool = True
    app_auto_seed_system: bool = True
    app_run_scheduler: bool = False
    app_run_activity_engine: bool = False
    mcp_enabled: bool = False
    plugin_system_enabled: bool = False
    ambient_monitor_enabled: bool = False

    # Multi-channel messaging
    channels_enabled: str = ""  # Comma-separated: "whatsapp,imessage"
    channel_auto_create_users: bool = True
    channel_default_scene: str = "study_session"

    # WhatsApp Cloud API
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""

    # iMessage via BlueBubbles
    bluebubbles_server_url: str = ""  # e.g. http://localhost:1234
    bluebubbles_password: str = ""
    bluebubbles_webhook_secret: str = ""

    # Telegram Bot API
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""  # Default chat ID for outbound notifications

    # Discord Bot
    discord_bot_token: str = ""
    discord_application_id: str = ""
    discord_public_key: str = ""

    # Notification push
    push_notifications_enabled: bool = False
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claims_email: str = ""

    # Rate limiting
    rate_limit_mode: str = "simple"  # "simple" | "cost_aware"
    rate_limit_cost_budget: int = 500  # cost units per minute per IP (cost_aware mode)
    trust_proxy_headers: bool = False  # Trust X-Forwarded-For header (only enable behind a reverse proxy)

    # Swarm / parallel execution
    swarm_enabled: bool = True
    swarm_max_concurrency: int = 4
    swarm_timeout_seconds: float = 30.0
    swarm_token_budget: int = 50000
    parallel_context_loading: bool = True
    activity_engine_max_concurrency: int = 3
    activity_use_redis_notify: bool = False

    # Phase 3: Multi-modal
    screenpipe_enabled: bool = False  # Enable Screenpipe screen context integration

    # Web search
    tavily_api_key: str = ""

    # Workspace (agent file operations)
    workspace_max_size_mb: int = 500

    # Code sandbox
    code_sandbox_backend: str = "auto"  # container | auto | process
    code_sandbox_runtime: str = "docker"  # docker | podman
    code_sandbox_image: str = "python:3.11-alpine"
    code_sandbox_timeout_seconds: int = 5
    allow_insecure_process_sandbox: bool = False

    # Encryption (Fernet key for at-rest encryption of OAuth tokens etc.)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # Cognitive load signal weights (sum should = 1.0)
    # Source: "Cognitive Load Theory meets Deep Knowledge Tracing" (Nature, 2025)
    cognitive_load_weight_fatigue: float = 0.25
    cognitive_load_weight_session_length: float = 0.15
    cognitive_load_weight_errors: float = 0.20
    cognitive_load_weight_brevity: float = 0.10
    cognitive_load_weight_help_seeking: float = 0.15
    cognitive_load_weight_quiz_performance: float = 0.15
    cognitive_load_threshold_high: float = 0.6
    cognitive_load_threshold_medium: float = 0.3

    # LECTOR review priority factors
    lector_factor_low_mastery: float = 0.5       # Multiplier for (0.8 - mastery)
    lector_factor_never_practiced: float = 0.3   # Bonus for unpracticed concepts
    lector_factor_time_decay: float = 0.3        # Memory decay weight
    lector_factor_prerequisite: float = 0.2      # Weak prerequisite boost
    lector_factor_confusion: float = 0.1         # Confusion pair boost
    lector_mastery_threshold: float = 0.8        # Below this = needs review
    lector_prerequisite_threshold: float = 0.5   # Prereq mastery alert level
    lector_confusion_threshold: float = 0.6      # Confusion pair mastery alert

    # Logging
    log_file: str = ""  # Path to log file; empty = stdout only
    log_max_bytes: int = 10_485_760  # 10 MB
    log_backup_count: int = 5

    # Google Calendar Integration (OAuth2)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/integrations/google-calendar/callback"

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def enabled_channels(self) -> list[str]:
        if not self.channels_enabled.strip():
            return []
        return self._split_csv(self.channels_enabled)

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return self._split_csv(self.cors_origins)

    @model_validator(mode="after")
    def _resolve_database_url(self):
        """Resolve database URL: fallback to SQLite, normalize PG schemes.

        - Empty/unset DATABASE_URL → SQLite at ~/.opentutor/data.db (lazy dir creation)
        - postgres:// → postgresql+asyncpg:// (Render/Railway compat)
        - postgresql:// → postgresql+asyncpg:// (missing driver suffix)
        """
        if not self.database_url:
            data_dir = Path.home() / ".opentutor"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite+aiosqlite:///{data_dir / 'data.db'}"
        elif self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql+asyncpg://", 1
            )
        elif self.database_url.startswith("postgresql://") and "+asyncpg" not in self.database_url:
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        return self

    @model_validator(mode="after")
    def _validate_security(self):
        if self.auth_enabled:
            if self.jwt_secret_key == "change-me-in-production":
                raise ValueError(
                    "jwt_secret_key must be changed from the default when auth is enabled"
                )
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "jwt_secret_key must be at least 32 characters when auth is enabled"
                )
        if self.environment == "production":
            if self.jwt_secret_key == "change-me-in-production":
                raise ValueError(
                    "jwt_secret_key must be changed from the default in production"
                )
            if "REDACTED_DEV_PASSWORD" in self.database_url:
                raise ValueError(
                    "Default database password must be changed in production"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
