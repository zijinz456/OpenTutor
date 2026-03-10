"""Application configuration via environment variables."""

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"

    # Database (SQLite-only local mode) — defaults to ~/.opentutor/data.db if DATABASE_URL not set
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
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # CORS
    cors_origins: str = "http://localhost:3001,http://127.0.0.1:3001"

    # File Upload
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50
    scrape_fixture_dir: str = ""

    # Runtime bootstrap
    app_auto_create_tables: bool = True
    app_auto_seed_system: bool = True
    app_run_scheduler: bool = False
    app_run_activity_engine: bool = False
    ambient_monitor_enabled: bool = True
    enable_experimental_loom: bool = True
    enable_experimental_lector: bool = True
    enable_experimental_notion_export: bool = False

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

    # Web search
    tavily_api_key: str = ""

    # Workspace (agent file operations)
    workspace_max_size_mb: int = 500

    # Code sandbox
    code_sandbox_backend: str = "auto"  # container | auto | process
    code_sandbox_runtime: str = "docker"  # docker | podman
    code_sandbox_image: str = "python:3.11-alpine"
    code_sandbox_timeout_seconds: int = 5
    allow_insecure_process_sandbox: bool = False  # Allows raw subprocess sandbox (no container isolation)

    # Encryption (Fernet key for at-rest encryption of OAuth tokens etc.)
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # Cognitive load signal weights (sum = 1.0)
    # Source: "Cognitive Load Theory meets Deep Knowledge Tracing" (Nature, 2025)
    # Proportionally normalized from original paper weights to sum to 1.0
    cognitive_load_weight_fatigue: float = 0.18
    cognitive_load_weight_session_length: float = 0.11
    cognitive_load_weight_errors: float = 0.15
    cognitive_load_weight_brevity: float = 0.07
    cognitive_load_weight_help_seeking: float = 0.11
    cognitive_load_weight_quiz_performance: float = 0.11
    cognitive_load_weight_answer_hesitation: float = 0.07
    cognitive_load_weight_nlp_affect: float = 0.11
    cognitive_load_weight_relative_baseline: float = 0.09
    cognitive_load_threshold_high: float = 0.6
    cognitive_load_threshold_medium: float = 0.3

    # Cognitive load normalization constants
    cognitive_load_session_messages_norm: float = 40.0     # ~40 messages ≈ 45 min
    cognitive_load_error_count_norm: float = 5.0           # 5+ unmastered errors = max signal
    cognitive_load_brevity_length_norm: float = 100.0      # <100 chars = some signal
    cognitive_load_quiz_accuracy_target: float = 0.7       # Below 70% accuracy = signal
    cognitive_load_hesitation_min_ms: float = 15000.0      # 15s = no signal
    cognitive_load_hesitation_range_ms: float = 45000.0    # 60s+ = full signal
    cognitive_load_nlp_frustration_weight: float = 0.6
    cognitive_load_nlp_confusion_weight: float = 0.4
    cognitive_load_review_reorder_threshold: float = 0.5

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
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return self._split_csv(self.cors_origins)

    @model_validator(mode="after")
    def _resolve_database_url(self):
        """Resolve database URL in SQLite-only local mode.

        - Empty/unset DATABASE_URL → SQLite at ~/.opentutor/data.db (lazy dir creation)
        - DATABASE_URL must be a sqlite URL when explicitly set
        """
        if not self.database_url:
            data_dir = Path.home() / ".opentutor"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite+aiosqlite:///{data_dir / 'data.db'}"
        elif self.database_url.startswith("sqlite"):
            for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
                if self.database_url.startswith(prefix):
                    sqlite_path = self.database_url[len(prefix):]
                    if sqlite_path.startswith("~"):
                        self.database_url = f"{prefix}{Path(sqlite_path).expanduser()}"
                    break
        else:
            raise ValueError(
                "SQLite-only local mode requires DATABASE_URL to be empty or start with sqlite"
            )
        return self

    @model_validator(mode="after")
    def _validate_security(self):
        import logging as _logging

        _log = _logging.getLogger("opentutor.config")

        # Generate a random CSRF signing key when jwt_secret_key is not set
        # (CSRF middleware needs a signing key even when auth is disabled)
        if not self.jwt_secret_key:
            import secrets as _secrets
            self.jwt_secret_key = _secrets.token_hex(32)

        if self.auth_enabled:
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "jwt_secret_key must be at least 32 characters when auth is enabled"
                )
        elif self.environment != "development":
            _log.warning(
                "SECURITY WARNING: auth_enabled=False in '%s' environment. "
                "Anyone with network access can use this instance without authentication. "
                "Set AUTH_ENABLED=true and configure JWT_SECRET_KEY for production use.",
                self.environment,
            )

        if self.environment in ("production", "staging"):
            if self.auth_enabled:
                env_key = os.environ.get("JWT_SECRET_KEY", "")
                if not env_key or len(env_key) < 32:
                    raise ValueError(
                        "JWT_SECRET_KEY must be explicitly set (>= 32 chars) in production with auth enabled"
                    )
            if "opentutor_dev" in self.database_url:
                raise ValueError(
                    "Default database password must be changed in production"
                )
            # Require encryption_key when OAuth integrations are configured
            has_oauth = bool(self.google_client_id and self.google_client_secret)
            if has_oauth and not self.encryption_key:
                raise ValueError(
                    "encryption_key is required in production when OAuth integrations "
                    "are configured (Google Calendar, etc.). Generate one with: "
                    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
