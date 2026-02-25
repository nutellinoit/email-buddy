"""Tests for Pydantic configuration validation."""

import pytest
from pydantic import ValidationError

from src.config import Config


def _make_config(**overrides):
    """Create a Config instance with test defaults + overrides."""
    defaults = {
        "IMAP_USERNAME": "test@example.com",
        "IMAP_PASSWORD": "testpass",
    }
    defaults.update(overrides)
    return Config(**defaults)


class TestPortValidation:
    def test_valid_ports(self):
        for port in (1, 993, 65535):
            cfg = _make_config(IMAP_PORT=port)
            assert port == cfg.IMAP_PORT

    def test_invalid_port_zero(self):
        with pytest.raises(ValidationError):
            _make_config(IMAP_PORT=0)

    def test_invalid_port_negative(self):
        with pytest.raises(ValidationError):
            _make_config(IMAP_PORT=-1)

    def test_invalid_port_too_high(self):
        with pytest.raises(ValidationError):
            _make_config(IMAP_PORT=65536)


class TestCategoriesValidation:
    def test_default_categories(self):
        cfg = _make_config()
        assert len(cfg.CATEGORIES) == 3
        assert cfg.category_names == ["spam", "newsletter", "regular"]
        assert cfg.default_category.name == "regular"

    def test_custom_categories(self):
        cats = [
            {"name": "spam", "folder": "Junk", "threshold": 0.8, "description": "Bad stuff"},
            {"name": "orders", "folder": "Orders", "threshold": 0.7, "description": "Purchase orders"},
            {"name": "regular", "folder": "", "threshold": 0.5, "description": "Normal", "is_default": True},
        ]
        cfg = _make_config(CATEGORIES=cats)
        assert cfg.category_names == ["spam", "orders", "regular"]
        assert cfg.default_category.name == "regular"
        assert cfg.category_map["orders"].folder == "Orders"

    def test_duplicate_names_rejected(self):
        cats = [
            {"name": "spam", "folder": "A"},
            {"name": "spam", "folder": "B", "is_default": True},
        ]
        with pytest.raises(ValidationError):
            _make_config(CATEGORIES=cats)

    def test_no_default_rejected(self):
        cats = [
            {"name": "spam", "folder": "A"},
            {"name": "regular", "folder": ""},
        ]
        with pytest.raises(ValidationError):
            _make_config(CATEGORIES=cats)

    def test_multiple_defaults_rejected(self):
        cats = [
            {"name": "spam", "folder": "A", "is_default": True},
            {"name": "regular", "folder": "", "is_default": True},
        ]
        with pytest.raises(ValidationError):
            _make_config(CATEGORIES=cats)

    def test_invalid_threshold_in_category(self):
        cats = [
            {"name": "spam", "folder": "A", "threshold": 1.5, "is_default": True},
        ]
        with pytest.raises(ValidationError):
            _make_config(CATEGORIES=cats)

    def test_movable_categories(self):
        cfg = _make_config()
        movable = cfg.movable_categories
        assert all(not c.is_default for c in movable)
        assert len(movable) == 2  # spam and newsletter

    def test_get_folder_for_category(self):
        cfg = _make_config()
        assert cfg.get_folder_for_category("spam") == "Suspicious"
        assert cfg.get_folder_for_category("regular") is None


class TestPositiveIntValidation:
    def test_valid_positive_ints(self):
        cfg = _make_config(EMAIL_LIMIT=1, MAX_FETCH_BATCH=100, EMAIL_FETCH_DAYS=14)
        assert cfg.EMAIL_LIMIT == 1
        assert cfg.MAX_FETCH_BATCH == 100
        assert cfg.EMAIL_FETCH_DAYS == 14

    def test_invalid_zero(self):
        with pytest.raises(ValidationError):
            _make_config(EMAIL_LIMIT=0)

    def test_invalid_negative(self):
        with pytest.raises(ValidationError):
            _make_config(MAX_FETCH_BATCH=-1)

    def test_invalid_email_fetch_days_zero(self):
        with pytest.raises(ValidationError):
            _make_config(EMAIL_FETCH_DAYS=0)


class TestDailySummaryHourValidation:
    def test_valid_hours(self):
        for hour in (0, 8, 12, 23):
            cfg = _make_config(DAILY_SUMMARY_HOUR=hour)
            assert hour == cfg.DAILY_SUMMARY_HOUR

    def test_invalid_hour_negative(self):
        with pytest.raises(ValidationError):
            _make_config(DAILY_SUMMARY_HOUR=-1)

    def test_invalid_hour_too_high(self):
        with pytest.raises(ValidationError):
            _make_config(DAILY_SUMMARY_HOUR=24)

    def test_default_disabled(self):
        cfg = _make_config(DAILY_SUMMARY_ENABLED=False)
        assert cfg.DAILY_SUMMARY_ENABLED is False

    def test_default_hour(self):
        cfg = _make_config()
        assert cfg.DAILY_SUMMARY_HOUR == 8

    def test_default_summary_language(self):
        cfg = _make_config(DAILY_SUMMARY_LANGUAGE="English")
        assert cfg.DAILY_SUMMARY_LANGUAGE == "English"

    def test_custom_summary_language(self):
        cfg = _make_config(DAILY_SUMMARY_LANGUAGE="Italian")
        assert cfg.DAILY_SUMMARY_LANGUAGE == "Italian"


class TestImapCredentials:
    def test_validate_missing_username(self):
        cfg = _make_config(IMAP_USERNAME="", IMAP_PASSWORD="pass")
        errors = cfg.validate()
        assert any("IMAP_USERNAME" in e for e in errors)

    def test_validate_missing_password(self):
        cfg = _make_config(IMAP_USERNAME="user@test.com", IMAP_PASSWORD="")
        errors = cfg.validate()
        assert any("IMAP_PASSWORD" in e for e in errors)

    def test_validate_all_present(self):
        cfg = _make_config()
        errors = cfg.validate()
        assert errors == []


class TestDefaults:
    """Test defaults by passing explicit values (env vars from conftest override defaults)."""

    def test_default_litellm_model(self, monkeypatch):
        monkeypatch.delenv("LITELLM_MODEL", raising=False)
        cfg = _make_config()
        assert cfg.LITELLM_MODEL == "ollama/llama3.1:8b"

    def test_default_imap_port(self):
        cfg = _make_config()
        assert cfg.IMAP_PORT == 993

    def test_default_process_interval(self):
        # Explicit value overrides .env file
        cfg = _make_config(PROCESS_INTERVAL=3600)
        assert cfg.PROCESS_INTERVAL == 3600

    def test_default_dry_run(self):
        cfg = _make_config()
        assert cfg.DRY_RUN is False
