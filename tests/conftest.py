"""Shared fixtures for Email-Buddy test suite."""

import pytest


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
