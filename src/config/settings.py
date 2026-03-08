"""
Central configuration module loaded from environment variables via Pydantic-Settings.
All components import from here – never read os.environ directly elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings with validation and defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model name")
    openai_max_tokens: int = Field(default=2000, description="Max tokens per LLM call")

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: Optional[str] = Field(default=None, description="GitHub PAT")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./data/qa_agent.db", description="SQLAlchemy DB URL"
    )

    # ── Scheduler ─────────────────────────────────────────────────────────────
    schedule_interval_hours: int = Field(
        default=6, description="Run interval in hours"
    )

    # ── Notifications ─────────────────────────────────────────────────────────
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    notify_email: str = Field(default="")

    slack_bot_token: Optional[str] = Field(default=None)
    slack_channel: str = Field(default="#qa-intelligence")

    # ── Relevance ─────────────────────────────────────────────────────────────
    min_relevance_score: int = Field(
        default=50, ge=0, le=100, description="Minimum relevance score for AI summarization (0-100)"
    )

    # ── Report content ─────────────────────────────────────────────────────────
    max_articles_per_report: int = Field(
        default=30, ge=5, le=100,
        description="Maximum articles per report (REQ-02: target 20-30)",
    )
    min_articles_per_report: int = Field(
        default=20, ge=1, le=100,
        description="Minimum articles – log warning if fewer found (REQ-02)",
    )
    max_article_age_days: int = Field(
        default=90, ge=7, le=365,
        description="Maximum article age in days. Articles older than this are deprioritized/excluded.",
    )
    prioritize_recent_articles: bool = Field(
        default=True,
        description="If True, recent articles (< 30 days) get a score boost for ranking.",
    )

    # ── Language ───────────────────────────────────────────────────────────────
    report_language: str = Field(
        default="English",
        description=(
            "Output language for AI summaries, insights, and trend analysis. "
            "Examples: 'English', 'Hebrew', 'Spanish'. (REQ-04)"
        ),
    )

    # ── Reports ───────────────────────────────────────────────────────────────
    reports_dir: Path = Field(default=Path("./reports"))

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    log_dir: Path = Field(default=Path("./logs"))

    def ensure_dirs(self) -> None:
        """Create required directories if they do not exist."""
        for directory in [self.reports_dir, self.log_dir, Path("./data")]:
            directory.mkdir(parents=True, exist_ok=True)


# Singleton – imported by all modules
settings = Settings()
settings.ensure_dirs()
