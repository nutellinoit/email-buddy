"""Tests for ProcessedEmail and LearningData models."""

from src.models import LearningData, ProcessedEmail


class TestProcessedEmail:
    def test_from_email_data_with_content_id(self, sample_email_data):
        pe = ProcessedEmail.from_email_data(sample_email_data, "spam", 0.95, "Suspicious content")
        assert pe.email_id == "abc123hash"
        assert pe.content_hash == "abc123hash"
        assert pe.subject == "Test Email Subject"
        assert pe.sender == "John Doe <john@example.com>"
        assert pe.classification == "spam"
        assert pe.confidence == 0.95

    def test_from_email_data_without_content_id(self):
        data = {"subject": "Test", "sender": "a@b.com", "body": "hello"}
        pe = ProcessedEmail.from_email_data(data, "regular", 0.8, "OK")
        # Should generate MD5 hash
        assert pe.email_id == pe.content_hash
        assert len(pe.content_hash) == 32  # MD5 hex length

    def test_hash_consistency(self):
        data = {"subject": "Same", "sender": "same@test.com", "body": "same body"}
        pe1 = ProcessedEmail.from_email_data(data, "regular", 0.8, "OK")
        pe2 = ProcessedEmail.from_email_data(data, "spam", 0.9, "Different reason")
        assert pe1.content_hash == pe2.content_hash

    def test_to_dict_excludes_id(self, sample_email_data):
        pe = ProcessedEmail.from_email_data(sample_email_data, "regular", 0.9, "OK")
        d = pe.to_dict()
        assert "id" not in d
        assert "email_id" in d
        assert "classification" in d

    def test_missing_fields_use_defaults(self):
        pe = ProcessedEmail.from_email_data({}, "regular", 0.5, "fallback")
        assert pe.subject == ""
        assert pe.sender == ""
        assert pe.message_id == ""


class TestLearningData:
    def test_determine_learning_type_false_positive_spam(self):
        assert LearningData._determine_learning_type("Suspicious", "regular") == "false_positive_spam"

    def test_determine_learning_type_false_positive_newsletter(self):
        assert LearningData._determine_learning_type("Newsletters", "regular") == "false_positive_newsletter"

    def test_determine_learning_type_false_negative_spam(self):
        assert LearningData._determine_learning_type("INBOX", "spam") == "false_negative_spam"

    def test_determine_learning_type_false_negative_newsletter(self):
        assert LearningData._determine_learning_type("INBOX", "newsletter") == "false_negative_newsletter"

    def test_determine_learning_type_unknown(self):
        assert LearningData._determine_learning_type("Other", "spam") == "unknown"

    def test_from_email_data_extracts_domain(self, sample_email_data):
        ld = LearningData.from_email_data(sample_email_data, "INBOX", "spam", "Learned rule")
        assert ld.email_domain == "example.com"
        assert ld.learning_type == "false_negative_spam"

    def test_from_email_data_domain_with_angle_brackets(self):
        data = {"sender": "Name <user@domain.org>", "message_id": "x", "subject": "s"}
        ld = LearningData.from_email_data(data, "INBOX", "newsletter", "Rule")
        assert ld.email_domain == "domain.org"

    def test_from_email_data_no_at_sign(self):
        data = {"sender": "invalid-sender", "message_id": "x", "subject": "s"}
        ld = LearningData.from_email_data(data, "INBOX", "spam", "Rule")
        assert ld.email_domain == ""

    def test_to_dict_excludes_id(self, sample_email_data):
        ld = LearningData.from_email_data(sample_email_data, "Suspicious", "regular", "Rule")
        d = ld.to_dict()
        assert "id" not in d
        assert "learning_type" in d
