"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://opentutor:opentutor_dev@localhost:5432/opentutor"
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_provider: str = "openai"  # openai | anthropic | deepseek | ollama
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # File Upload
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 50

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
