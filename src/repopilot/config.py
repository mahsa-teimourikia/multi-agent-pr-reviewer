"""Runtime configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Credentials and model configuration for a ReviewForge deployment."""

    openai_api_key: str
    github_token: str | None = None
    github_repository: str | None = None
    review_model: str = "gpt-4o-mini"
    checkpoint_db: str = "reviewforge-checkpoints.sqlite"
    rate_limit_per_minute: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")
