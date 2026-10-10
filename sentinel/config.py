"""Application settings, loaded from environment variables and an optional .env file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

EMBEDDING_DIM = 1024  # Fixed by the database schema. voyage-law-2 and voyage-code-3 both emit 1024.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://sentinel:sentinel@localhost:54329/sentinel"
    redis_url: str = "redis://localhost:63799/0"

    llm_mode: Literal["auto", "anthropic", "offline"] = "auto"
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort_extract: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_effort_assess: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    # USD per million tokens, used to log the cost of each run. Matches claude-opus-5-5 pricing.
    price_input_per_mtok: float = 4.0
    price_output_per_mtok: float = 20.0

    embedding_provider: Literal["auto", "voyage", "hash"] = "auto"
    voyage_api_key: str = ""
    voyage_law_model: str = "voyage-law-2"
    voyage_code_model: str = "voyage-code-3"
    rerank_model: str = "rerank-2"

    auth_mode: Literal["clerk", "dev"] = "dev"
    clerk_secret_key: str = ""
    clerk_jwt_key: str = ""
    clerk_authorized_parties: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    clerk_webhook_signing_secret: str = ""
    internal_api_token: str = ""

    storage_backend: Literal["local", "s3"] = "local"
    data_dir: Path = Path("./data")
    s3_bucket: str = ""

    resend_api_key: str = ""
    alert_from_email: str = "sentinel@example.com"
    dashboard_url: str = "http://localhost:3000"

    require_approval: bool = True
    # Run audits in the API process instead of the queue (local dev and tests only).
    jobs_inline: bool = False
    confidence_threshold: float = 0.6
    scrape_user_agent: str = (
        "ComplianceSentinel/0.1 (+https://github.com/princhal/compliance-sentinel)"
    )
    scrape_min_delay_s: float = 2.0

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def _split_parties(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.environment == "production":
            if self.auth_mode != "clerk":
                raise ValueError("AUTH_MODE=dev is not allowed when ENVIRONMENT=production")
            if not (self.clerk_secret_key or self.clerk_jwt_key):
                raise ValueError("Clerk keys are required in production")
        return self

    @property
    def use_anthropic(self) -> bool:
        if self.llm_mode == "anthropic":
            return True
        if self.llm_mode == "offline":
            return False
        # An unset ANTHROPIC_API_KEY does not mean there are no credentials: the SDK also reads
        # ANTHROPIC_AUTH_TOKEN and profiles created by `ant auth login`.
        return bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")
            or (Path.home() / ".config" / "anthropic").exists()
        )

    @property
    def use_voyage(self) -> bool:
        if self.embedding_provider == "voyage":
            return True
        return self.embedding_provider == "auto" and bool(self.voyage_api_key)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"


@lru_cache
def get_settings() -> Settings:
    return Settings()
