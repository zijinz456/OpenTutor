"""Application configuration via environment variables."""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"

    # Database
    database_url: str = "postgresql+asyncpg://opentutor:REDACTED_DEV_PASSWORD@localhost:5432/opentutor"

    # LLM — primary provider selection
    llm_provider: str = "openai"  # openai | anthropic | deepseek | ollama | openrouter | gemini | groq | vllm | lmstudio | textgenwebui | custom
    llm_model: str = "gpt-4o-mini"

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

    # Model size routing (agent preference hints)
    llm_model_large: str = ""   # e.g. gpt-4o for teaching/planning agents
    llm_model_small: str = ""   # e.g. gpt-4o-mini for preference/scene agents
    llm_required: bool = False

    # Authentication
    auth_enabled: bool = False
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # CORS
    cors_origins: str = "http://localhost:3000"

    # File Upload
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50
    scrape_fixture_dir: str = ""

    # Runtime bootstrap
    app_auto_create_tables: bool = False
    app_auto_seed_system: bool = False
    app_run_scheduler: bool = False
    app_run_activity_engine: bool = False

    # Code sandbox
    code_sandbox_backend: str = "auto"  # auto | container | process
    code_sandbox_runtime: str = "docker"  # docker | podman
    code_sandbox_image: str = "python:3.11-alpine"
    code_sandbox_timeout_seconds: int = 5

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validate_jwt_secret(self):
        if self.auth_enabled:
            if self.jwt_secret_key == "change-me-in-production":
                raise ValueError(
                    "jwt_secret_key must be changed from the default when auth is enabled"
                )
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "jwt_secret_key must be at least 32 characters when auth is enabled"
                )
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
