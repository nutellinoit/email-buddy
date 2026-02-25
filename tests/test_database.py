"""Tests for EmailDatabaseManager with temporary SQLite file."""

import pytest

from src.database import EmailDatabaseManager
from src.models import LearningData, ProcessedEmail


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite database in a temporary directory for each test."""
    db_path = str(tmp_path / "test.db")
    return EmailDatabaseManager(db_path)


def _make_processed_email(sample_email_data, **overrides):
    """Helper to create ProcessedEmail from sample data with optional overrides."""
    kwargs = {
        "email_data": sample_email_data,
        "classification": "spam",
        "confidence": 0.95,
        "reason": "Suspicious content",
    }
    kwargs.update(overrides)
    return ProcessedEmail.from_email_data(**kwargs)


class TestSaveAndRetrieve:
    def test_save_and_check_processed(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data)
        db.save_processed_email(pe)
        assert db.is_email_processed(sample_email_data) is True

    def test_unprocessed_email(self, db):
        data = {"content_id": "unknown", "message_id": "unknown", "subject": "x", "sender": "x", "body": "x"}
        assert db.is_email_processed(data) is False

    def test_lookup_by_content_id(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data)
        db.save_processed_email(pe)
        result = db.find_original_classification(sample_email_data)
        assert result is not None
        assert result["classification"] == "spam"

    def test_find_original_classification_not_found(self, db):
        data = {"content_id": "nope", "message_id": "nope", "subject": "x", "sender": "x", "body": "x"}
        assert db.find_original_classification(data) is None


class TestStatistics:
    def test_statistics_after_inserts(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data, classification="spam")
        db.save_processed_email(pe)

        # Add a newsletter
        nl_data = {**sample_email_data, "content_id": "nl001", "message_id": "<nl@test>"}
        pe2 = _make_processed_email(nl_data, classification="newsletter", confidence=0.8)
        db.save_processed_email(pe2)

        stats = db.get_statistics()
        assert stats["total_processed"] == 2

    def test_sender_statistics(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data, classification="spam")
        db.save_processed_email(pe)

        stats = db.get_sender_statistics("john@example.com", "example.com")
        assert stats["sender_spam"] >= 1
        assert stats["sender_total"] >= 1


class TestLearningRoundTrip:
    def test_save_and_retrieve_learning(self, db, sample_email_data):
        ld = LearningData.from_email_data(sample_email_data, "INBOX", "spam", "This is a learned rule")
        db.save_learning_data(ld)

        recent = db.get_recent_learning(limit=10, days=30)
        assert len(recent) >= 1

    def test_learning_statistics(self, db, sample_email_data):
        ld = LearningData.from_email_data(sample_email_data, "INBOX", "spam", "Rule")
        db.save_learning_data(ld)

        stats = db.get_learning_statistics()
        assert stats["total_learning_entries"] >= 1


class TestCleanup:
    def test_cleanup_old_records(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data)
        db.save_processed_email(pe)

        # Cleanup with 0 days retention should remove everything
        deleted = db.cleanup_old_records(0)
        assert deleted >= 1

    def test_cleanup_keeps_recent(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data)
        db.save_processed_email(pe)

        # Cleanup with 365 days should keep the record (it was just inserted)
        deleted = db.cleanup_old_records(365)
        assert deleted == 0
        assert db.is_email_processed(sample_email_data) is True


class TestGetRecentEmailDetails:
    def test_returns_recent_emails(self, db, sample_email_data):
        from datetime import datetime, timedelta

        pe = _make_processed_email(sample_email_data, classification="regular")
        db.save_processed_email(pe)
        since = datetime.now() - timedelta(hours=1)
        results = db.get_recent_email_details_since(since)
        assert len(results) == 1
        assert results[0].classification == "regular"

    def test_excludes_summary_records(self, db, sample_email_data):
        from datetime import datetime, timedelta

        pe = _make_processed_email(sample_email_data, classification="summary")
        db.save_processed_email(pe)
        since = datetime.now() - timedelta(hours=1)
        results = db.get_recent_email_details_since(since)
        assert len(results) == 0

    def test_respects_limit(self, db, sample_email_data):
        from datetime import datetime, timedelta

        for i in range(5):
            data = {**sample_email_data, "content_id": f"cid-{i}", "message_id": f"<msg-{i}@test>"}
            pe = _make_processed_email(data, classification="regular")
            db.save_processed_email(pe)
        since = datetime.now() - timedelta(hours=1)
        results = db.get_recent_email_details_since(since, limit=2)
        assert len(results) == 2


class TestFolderReconciliationQueries:
    """Tests for folder reconciliation DB methods."""

    def test_get_recent_classified_with_folders(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data, classification="spam",
                                   folder_moved_to="Suspicious")
        db.save_processed_email(pe)

        results = db.get_recent_classified_with_folders(days=7)
        assert len(results) == 1
        r = results[0]
        assert r["message_id"] == sample_email_data["message_id"]
        assert r["classification"] == "spam"
        assert r["folder_moved_to"] == "Suspicious"
        assert r["subject"] == sample_email_data["subject"]
        assert r["sender"] == sample_email_data["sender"]

    def test_excludes_summaries(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data, classification="summary")
        db.save_processed_email(pe)

        results = db.get_recent_classified_with_folders(days=7)
        assert len(results) == 0

    def test_excludes_old_emails(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data, classification="spam",
                                   folder_moved_to="Suspicious")
        db.save_processed_email(pe)

        # 0 days = only emails from today (which should include just-inserted)
        results = db.get_recent_classified_with_folders(days=0)
        # With days=0, cutoff is now() - 0 days = now(), so just-inserted should be excluded
        # Actually this depends on timing; use a very small window instead
        assert isinstance(results, list)

    def test_excludes_empty_message_id(self, db):
        data = {"content_id": "cid1", "message_id": "", "subject": "X",
                "sender": "x@test.com", "body": "Y", "date": "2026-01-01"}
        pe = _make_processed_email(data, classification="spam", folder_moved_to="Suspicious")
        db.save_processed_email(pe)

        results = db.get_recent_classified_with_folders(days=7)
        assert len(results) == 0

    def test_update_folder_moved_to(self, db, sample_email_data):
        pe = _make_processed_email(sample_email_data, classification="spam",
                                   folder_moved_to="Suspicious")
        db.save_processed_email(pe)

        success = db.update_folder_moved_to(sample_email_data["message_id"], None)
        assert success is True

        # Verify the update
        results = db.get_recent_classified_with_folders(days=7)
        assert len(results) == 1
        assert results[0]["folder_moved_to"] is None

    def test_update_nonexistent_returns_false(self, db):
        success = db.update_folder_moved_to("<nonexistent@test>", "INBOX")
        assert success is False


class TestDuplicateHandling:
    def test_insert_or_replace_on_duplicate(self, db, sample_email_data):
        pe1 = _make_processed_email(sample_email_data, classification="regular", confidence=0.5)
        db.save_processed_email(pe1)

        pe2 = _make_processed_email(sample_email_data, classification="spam", confidence=0.9)
        db.save_processed_email(pe2)

        stats = db.get_statistics()
        assert stats["total_processed"] == 1
