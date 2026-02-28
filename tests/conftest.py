"""Shared fixtures for Email-Buddy test suite."""

import json

import pytest

# Default categories matching src/config.py defaults — pinned here so tests
# are isolated from the user's .env file.
_DEFAULT_CATEGORIES = [
    {
        "name": "spam",
        "folder": "Suspicious",
        "threshold": 0.7,
        "description": "Unwanted, fraudulent, or malicious emails including phishing, scams, and unsolicited messages",
    },
    {
        "name": "newsletter",
        "folder": "Newsletters",
        "threshold": 0.7,
        "description": "Legitimate promotional and marketing emails including company newsletters, product announcements, and subscription content",
    },
    {
        "name": "regular",
        "folder": "",
        "threshold": 0.5,
        "description": "Personal and important emails including work correspondence, transactional notifications, and anything requiring personal attention",
        "is_default": True,
    },
]


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Set test environment variables before any config import."""
    monkeypatch.setenv("IMAP_USERNAME", "test@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "testpass")
    monkeypatch.setenv("LITELLM_MODEL", "ollama/test-model")
    monkeypatch.setenv("LITELLM_API_BASE", "http://localhost:11434")
    monkeypatch.setenv("LITELLM_API_KEY", "not-needed")
    monkeypatch.setenv("LITELLM_TIMEOUT", "300")
    monkeypatch.setenv("DATABASE_PATH", ":memory:")
    monkeypatch.setenv("CATEGORIES", json.dumps(_DEFAULT_CATEGORIES))

    # Rebuild the module-level config singleton so code that imports it
    # (e.g. LearningProcessor, LearningData) sees the test values.
    import src.config

    monkeypatch.setattr(src.config, "config", src.config.Config())


@pytest.fixture
def sample_email_data():
    """Sample email data dict for testing."""
    return {
        "id": "12345",
        "message_id": "<msg001@example.com>",
        "content_id": "abc123hash",
        "subject": "Test Email Subject",
        "sender": "John Doe <john@example.com>",
        "body": "This is a test email body with some content.",
        "date": "2026-01-15T10:30:00",
        "flags": ["\\Seen"],
    }


@pytest.fixture
def spam_email_data():
    """Sample spam email data."""
    return {
        "id": "99999",
        "message_id": "<spam001@shady.com>",
        "content_id": "spam123hash",
        "subject": "URGENT: You Won $1,000,000!!!",
        "sender": "winner@shady-deals.com",
        "body": "Click here to claim your prize! Send us your bank details.",
        "date": "2026-01-15T11:00:00",
    }


@pytest.fixture
def newsletter_email_data():
    """Sample newsletter email data."""
    return {
        "id": "88888",
        "message_id": "<news001@company.com>",
        "content_id": "news123hash",
        "subject": "Weekly Product Update - New Features!",
        "sender": "updates@company.com",
        "body": "Check out our latest features. Unsubscribe: click here.",
        "date": "2026-01-15T12:00:00",
    }


@pytest.fixture
def db_manager():
    """In-memory SQLite database manager."""
    from src.database import EmailDatabaseManager

    return EmailDatabaseManager(":memory:")
