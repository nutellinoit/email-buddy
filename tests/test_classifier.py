"""Tests for EmailClassifier pure methods and classification logic."""

from unittest.mock import MagicMock, patch

import pytest

from src.schemas import EmailClassification


class TestExtractSenderInfo:
    """Test _extract_sender_info (pure method)."""

    def _extract(self, sender):
        from src.email_classifier import EmailClassifier

        # Use the method without full init by creating a minimal instance
        with (
            patch("src.email_classifier.get_database_manager"),
            patch("src.email_classifier.get_model_name", return_value="test"),
        ):
            clf = EmailClassifier()
        return clf._extract_sender_info(sender)

    def test_name_and_email(self):
        email, domain = self._extract("John Doe <john@example.com>")
        assert email == "john@example.com"
        assert domain == "example.com"

    def test_email_only(self):
        email, domain = self._extract("john@example.com")
        assert email == "john@example.com"
        assert domain == "example.com"

    def test_no_at_sign(self):
        _email, domain = self._extract("invalid-sender")
        assert domain == ""

    def test_empty_string(self):
        _email, domain = self._extract("")
        assert domain == ""


class TestPrepareEmailContent:
    """Test _prepare_email_content (pure method)."""

    def _prepare(self, email_data):
        from src.email_classifier import EmailClassifier

        with (
            patch("src.email_classifier.get_database_manager"),
            patch("src.email_classifier.get_model_name", return_value="test"),
        ):
            clf = EmailClassifier()
        return clf._prepare_email_content(email_data)

    def test_extracts_fields(self, sample_email_data):
        content = self._prepare(sample_email_data)
        assert content["subject"] == "Test Email Subject"
        assert content["sender"] == "John Doe <john@example.com>"
        assert "test email body" in content["body"].lower()

    def test_truncates_body(self):
        data = {"body": "x" * 3000}
        content = self._prepare(data)
        assert len(content["body"]) == 2000

    def test_missing_fields_default_empty(self):
        content = self._prepare({})
        assert content["subject"] == ""
        assert content["sender"] == ""
        assert content["body"] == ""
        assert content["date"] == ""


class TestBuildHistoricalContext:
    """Test _build_historical_context (pure method)."""

    def _build(self, sender_email, sender_domain, stats):
        from src.email_classifier import EmailClassifier

        with (
            patch("src.email_classifier.get_database_manager"),
            patch("src.email_classifier.get_model_name", return_value="test"),
        ):
            clf = EmailClassifier()
        return clf._build_historical_context(sender_email, sender_domain, stats)

    def _empty_stats(self):
        return {
            "sender_total": 0,
            "sender_spam": 0,
            "sender_newsletter": 0,
            "sender_regular": 0,
            "domain_total": 0,
            "domain_spam": 0,
            "domain_newsletter": 0,
            "domain_regular": 0,
        }

    def test_no_history(self):
        ctx = self._build("a@b.com", "b.com", self._empty_stats())
        assert "No previous emails" in ctx

    def test_sender_with_spam_history(self):
        stats = self._empty_stats()
        stats["sender_total"] = 5
        stats["sender_spam"] = 5
        ctx = self._build("a@b.com", "b.com", stats)
        assert "SENDER HISTORY" in ctx
        assert "5 spam" in ctx
        assert "primarily sent spam" in ctx

    def test_sender_with_newsletter_history(self):
        stats = self._empty_stats()
        stats["sender_total"] = 3
        stats["sender_newsletter"] = 3
        ctx = self._build("a@b.com", "b.com", stats)
        assert "newsletter" in ctx.lower()

    def test_domain_history_included(self):
        stats = self._empty_stats()
        stats["domain_total"] = 10
        stats["domain_regular"] = 10
        ctx = self._build("a@b.com", "b.com", stats)
        assert "DOMAIN HISTORY" in ctx


class TestClassifyWithFallback:
    """Test classify_with_fallback with mocked LLM."""

    @pytest.fixture
    def classifier(self):
        with (
            patch("src.email_classifier.get_database_manager") as mock_db,
            patch("src.email_classifier.get_model_name", return_value="test"),
        ):
            mock_db.return_value = MagicMock()
            mock_db.return_value.get_sender_statistics.return_value = {
                "sender_total": 0,
                "sender_spam": 0,
                "sender_newsletter": 0,
                "sender_regular": 0,
                "domain_total": 0,
                "domain_spam": 0,
                "domain_newsletter": 0,
                "domain_regular": 0,
            }
            mock_db.return_value.get_recent_learning.return_value = []
            from src.email_classifier import EmailClassifier

            clf = EmailClassifier()
        return clf

    @patch("src.email_classifier.is_llm_available", return_value=True)
    @patch("src.email_classifier.llm_complete_structured")
    def test_spam_above_threshold(self, mock_llm, mock_avail, classifier, sample_email_data):
        mock_llm.return_value = EmailClassification(category="spam", confidence=0.95, reason="Phishing")
        with patch.object(classifier, "db_manager") as mock_db:
            mock_db.get_sender_statistics.return_value = {
                "sender_total": 0,
                "sender_spam": 0,
                "sender_newsletter": 0,
                "sender_regular": 0,
                "domain_total": 0,
                "domain_spam": 0,
                "domain_newsletter": 0,
                "domain_regular": 0,
            }
            result = classifier.classify_with_fallback(sample_email_data)
        assert result is not None
        category, confidence, _reason = result
        assert category == "spam"
        assert confidence >= 0.85

    @patch("src.email_classifier.is_llm_available", return_value=True)
    @patch("src.email_classifier.llm_complete_structured")
    def test_regular_returned(self, mock_llm, mock_avail, classifier, sample_email_data):
        mock_llm.return_value = EmailClassification(category="regular", confidence=0.9, reason="Personal")
        with patch.object(classifier, "db_manager") as mock_db:
            mock_db.get_sender_statistics.return_value = {
                "sender_total": 0,
                "sender_spam": 0,
                "sender_newsletter": 0,
                "sender_regular": 0,
                "domain_total": 0,
                "domain_spam": 0,
                "domain_newsletter": 0,
                "domain_regular": 0,
            }
            result = classifier.classify_with_fallback(sample_email_data)
        category, _confidence, _reason = result
        assert category == "regular"

    @patch("src.email_classifier.is_llm_available", return_value=False)
    def test_llm_unavailable_returns_none(self, mock_avail, classifier, sample_email_data):
        result = classifier.classify_with_fallback(sample_email_data)
        assert result is None
