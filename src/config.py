"""
Configuration settings for Email-Buddy email processor.
Uses pydantic-settings for automatic env var loading and validation.
"""

from typing import Optional

from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CategoryConfig(BaseModel):
    """Configuration for a single email category."""

    name: str
    folder: str = ""
    threshold: float = 0.7
    description: str = ""
    is_default: bool = False

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("Category threshold must be between 0 and 1")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Category name must be alphanumeric (hyphens and underscores allowed)")
        return v.lower()


class Config(BaseSettings):
    """Configuration for Email-Buddy email processor."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Email/IMAP Configuration
    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_USERNAME: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_USE_SSL: bool = True

    # Email Folders
    INBOX_FOLDER: str = "INBOX"
    CATEGORY_FOLDERS_UNDER_INBOX: bool = False

    # LLM Configuration (LiteLLM unified — provider is inferred from model prefix)
    LITELLM_MODEL: str = "ollama/llama3.1:8b"
    LITELLM_API_BASE: str = "http://ollama:11434"
    LITELLM_API_KEY: str = "not-needed"
    LITELLM_TIMEOUT: int = 300

    # Processing Configuration
    EMAIL_LIMIT: int = 5
    EMAIL_FETCH_DAYS: int = 7
    DRY_RUN: bool = False
    PROCESS_INTERVAL: int = 3600
    IDLE_ENABLED: bool = True
    MARK_AS_READ_WHEN_MOVE: bool = True

    # Logging Configuration
    LOG_LEVEL: str = "INFO"

    # Categories Configuration (JSON array from env, parsed into list)
    CATEGORIES: list[CategoryConfig] = [
        CategoryConfig(
            name="spam",
            folder="Suspicious",
            threshold=0.7,
            description="Unwanted, fraudulent, or malicious emails including phishing, scams, and unsolicited messages",
        ),
        CategoryConfig(
            name="newsletter",
            folder="Newsletters",
            threshold=0.7,
            description="Legitimate promotional and marketing emails including company newsletters, product announcements, and subscription content",
        ),
        CategoryConfig(
            name="regular",
            folder="",
            threshold=0.5,
            description="Personal and important emails including work correspondence, transactional notifications, and anything requiring personal attention",
            is_default=True,
        ),
    ]

    # Database Configuration
    DATABASE_PATH: str = "/app/data/email_buddy.db"
    MAX_FETCH_BATCH: int = 20

    # Learning System Configuration
    LEARNING_ENABLED: bool = True
    LEARNING_RETENTION_DAYS: int = 0
    MAX_LEARNING_CONTEXT: int = 10

    # Email Retention Configuration
    EMAIL_RETENTION_DAYS: int = 365

    # Email Backup Configuration
    EMAIL_BACKUP_ENABLED: bool = False
    EMAIL_BACKUP_PATH: str = "/app/data/emails"

    # Daily Summary Configuration
    DAILY_SUMMARY_ENABLED: bool = False
    DAILY_SUMMARY_HOUR: int = 8
    DAILY_SUMMARY_LANGUAGE: str = "English"

    @field_validator("IMAP_PORT")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("IMAP_PORT must be between 1 and 65535")
        return v

    @field_validator(
        "EMAIL_LIMIT",
        "EMAIL_FETCH_DAYS",
        "MAX_FETCH_BATCH",
        "MAX_LEARNING_CONTEXT",
        "EMAIL_RETENTION_DAYS",
    )
    @classmethod
    def validate_positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Value must be greater than 0")
        return v

    @field_validator("LEARNING_RETENTION_DAYS")
    @classmethod
    def validate_learning_retention(cls, v: int) -> int:
        if v < 0:
            raise ValueError("LEARNING_RETENTION_DAYS must be >= 0 (0 = keep forever)")
        return v

    @field_validator("DAILY_SUMMARY_HOUR")
    @classmethod
    def validate_summary_hour(cls, v: int) -> int:
        if not (0 <= v <= 23):
            raise ValueError("DAILY_SUMMARY_HOUR must be between 0 and 23")
        return v

    @model_validator(mode="after")
    def validate_categories(self) -> "Config":
        """Validate category configuration."""
        names = [c.name for c in self.CATEGORIES]
        if len(names) != len(set(names)):
            raise ValueError("Category names must be unique")
        defaults = [c for c in self.CATEGORIES if c.is_default]
        if len(defaults) != 1:
            raise ValueError("Exactly one category must have is_default=True")
        return self

    @property
    def category_names(self) -> list[str]:
        """List of all category names."""
        return [c.name for c in self.CATEGORIES]

    @property
    def category_map(self) -> dict[str, CategoryConfig]:
        """Map of category name to CategoryConfig."""
        return {c.name: c for c in self.CATEGORIES}

    @property
    def default_category(self) -> CategoryConfig:
        """The default category (emails classified here are not moved)."""
        return next(c for c in self.CATEGORIES if c.is_default)

    @property
    def movable_categories(self) -> list[CategoryConfig]:
        """Categories whose emails should be moved (non-default)."""
        return [c for c in self.CATEGORIES if not c.is_default]

    def get_folder_for_category(self, category_name: str) -> Optional[str]:
        """Get the IMAP folder for a category. Returns None for default category."""
        cat = self.category_map.get(category_name)
        if cat and cat.folder:
            return cat.folder
        return None

    def validate(self) -> list:
        """Backward-compatible validation.

        Pydantic validates at construction time, so if this method is called
        the config is already valid. Kept for callers that check config.validate().
        Only checks fields that have empty-string defaults (IMAP credentials).
        """
        errors = []
        if not self.IMAP_USERNAME:
            errors.append("IMAP_USERNAME is required")
        if not self.IMAP_PASSWORD:
            errors.append("IMAP_PASSWORD is required")
        return errors


config = Config()
