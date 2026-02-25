"""Tests for LLM response schemas."""

import pytest
from pydantic import ValidationError

from src.schemas import EmailClassification, LearningSummary


class TestEmailClassification:
    def test_valid_spam(self):
        ec = EmailClassification(category="spam", confidence=0.95, reason="Phishing attempt")
        assert ec.category == "spam"
        assert ec.confidence == 0.95

    def test_valid_newsletter(self):
        ec = EmailClassification(category="newsletter", confidence=0.8, reason="Marketing content")
        assert ec.category == "newsletter"

    def test_valid_regular(self):
        ec = EmailClassification(category="regular", confidence=0.7, reason="Personal email")
        assert ec.category == "regular"

    def test_invalid_category(self):
        with pytest.raises(ValidationError):
            EmailClassification(category="invalid", confidence=0.5, reason="test")

    def test_confidence_too_high(self):
        with pytest.raises(ValidationError):
            EmailClassification(category="spam", confidence=1.5, reason="test")

    def test_confidence_too_low(self):
        with pytest.raises(ValidationError):
            EmailClassification(category="spam", confidence=-0.1, reason="test")

    def test_confidence_boundaries(self):
        ec_zero = EmailClassification(category="spam", confidence=0.0, reason="test")
        ec_one = EmailClassification(category="spam", confidence=1.0, reason="test")
        assert ec_zero.confidence == 0.0
        assert ec_one.confidence == 1.0


class TestLearningSummary:
    def test_valid_summary(self):
        ls = LearningSummary(summary="This sender is legitimate")
        assert ls.summary == "This sender is legitimate"
