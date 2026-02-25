"""Tests for LearningProcessor folder reconciliation workflow."""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_processor():
    """Create a LearningProcessor with mocked dependencies."""
    with (
        patch("src.learning.learning_processor.EmailClient"),
        patch("src.learning.learning_processor.get_database_manager"),
        patch("src.learning.learning_processor.LearningGenerator"),
    ):
        from src.learning.learning_processor import LearningProcessor

        proc = LearningProcessor()
    return proc


def _default_folder_to_class():
    """Default folder→classification map matching .env.example categories."""
    return {"INBOX": "regular", "Newsletters": "newsletter", "Suspicious": "spam"}


# ---------------------------------------------------------------------------
# TestBuildFolderMaps
# ---------------------------------------------------------------------------


class TestBuildFolderMaps:
    """Verify folder ↔ classification maps built from config."""

    def test_maps_default_to_inbox(self):
        proc = _make_processor()
        folder_to_class, class_to_folder = proc._build_folder_maps()

        assert folder_to_class["INBOX"] == "regular"
        assert class_to_folder["regular"] == "INBOX"

    def test_maps_non_default_to_folders(self):
        proc = _make_processor()
        folder_to_class, class_to_folder = proc._build_folder_maps()

        assert folder_to_class["Newsletters"] == "newsletter"
        assert folder_to_class["Suspicious"] == "spam"
        assert class_to_folder["newsletter"] == "Newsletters"
        assert class_to_folder["spam"] == "Suspicious"


# ---------------------------------------------------------------------------
# TestFindCorrections
# ---------------------------------------------------------------------------


class TestFindCorrections:
    """Verify correction detection logic (pure function, no mocks needed)."""

    def test_no_corrections_when_folders_match(self):
        proc = _make_processor()
        recent = [
            {"message_id": "<a@test>", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "Spam", "sender": "bad@test.com"},
        ]
        folder_emails = {"<a@test>": "Suspicious"}
        corrections = proc._find_corrections(recent, folder_emails, _default_folder_to_class())
        assert corrections == []

    def test_correction_detected(self):
        proc = _make_processor()
        recent = [
            {"message_id": "<a@test>", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "Not spam", "sender": "good@test.com"},
        ]
        # User moved the email from Suspicious to INBOX
        folder_emails = {"<a@test>": "INBOX"}
        corrections = proc._find_corrections(recent, folder_emails, _default_folder_to_class())

        assert len(corrections) == 1
        c = corrections[0]
        assert c["message_id"] == "<a@test>"
        assert c["old_classification"] == "spam"
        assert c["new_classification"] == "regular"
        assert c["old_folder"] == "Suspicious"
        assert c["new_folder"] == "INBOX"

    def test_skips_no_message_id(self):
        proc = _make_processor()
        recent = [
            {"message_id": "", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "X", "sender": "x@test.com"},
        ]
        folder_emails = {}
        corrections = proc._find_corrections(recent, folder_emails, _default_folder_to_class())
        assert corrections == []

    def test_skips_email_not_in_any_folder(self):
        proc = _make_processor()
        recent = [
            {"message_id": "<gone@test>", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "X", "sender": "x@test.com"},
        ]
        # Email not found in any scanned folder (deleted/archived)
        folder_emails = {}
        corrections = proc._find_corrections(recent, folder_emails, _default_folder_to_class())
        assert corrections == []

    def test_skips_unknown_folder(self):
        proc = _make_processor()
        recent = [
            {"message_id": "<a@test>", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "X", "sender": "x@test.com"},
        ]
        # Email found in a folder not in the folder_to_class map
        folder_emails = {"<a@test>": "Archive"}
        corrections = proc._find_corrections(recent, folder_emails, _default_folder_to_class())
        assert corrections == []

    def test_inbox_email_defaults_expected_folder(self):
        """Emails left in INBOX (folder_moved_to=None) should use INBOX as expected."""
        proc = _make_processor()
        recent = [
            {"message_id": "<a@test>", "email_id": "a1", "classification": "regular",
             "folder_moved_to": None, "subject": "X", "sender": "x@test.com"},
        ]
        # Still in INBOX → no correction
        folder_emails = {"<a@test>": "INBOX"}
        corrections = proc._find_corrections(recent, folder_emails, _default_folder_to_class())
        assert corrections == []


# ---------------------------------------------------------------------------
# TestReconcileFolders
# ---------------------------------------------------------------------------


class TestReconcileFolders:
    """Integration tests for the full reconcile_folders() workflow."""

    @patch("src.learning.learning_processor.config")
    def test_disabled_returns_disabled(self, mock_config):
        proc = _make_processor()
        mock_config.LEARNING_ENABLED = False

        result = proc.reconcile_folders()
        assert result["status"] == "disabled"

    @patch("src.learning.learning_processor.config")
    def test_llm_unavailable_returns_skipped(self, mock_config):
        proc = _make_processor()
        mock_config.LEARNING_ENABLED = True
        proc.learning_generator.is_available.return_value = False

        result = proc.reconcile_folders()
        assert result["status"] == "skipped"

    @patch("src.learning.learning_processor.config")
    def test_no_recent_emails(self, mock_config):
        proc = _make_processor()
        mock_config.LEARNING_ENABLED = True
        mock_config.EMAIL_FETCH_DAYS = 7
        mock_config.CATEGORIES = [
            MagicMock(name="regular", is_default=True, folder=""),
            MagicMock(name="spam", is_default=False, folder="Suspicious"),
        ]
        # Fix: MagicMock name attribute needs special handling
        mock_config.CATEGORIES[0].name = "regular"
        mock_config.CATEGORIES[1].name = "spam"
        mock_config.INBOX_FOLDER = "INBOX"
        proc.learning_generator.is_available.return_value = True
        proc.db_manager.get_recent_classified_with_folders.return_value = []

        # Mock _scan_all_folders to return empty dict
        with patch.object(proc, "_scan_all_folders", return_value={}):
            result = proc.reconcile_folders()

        assert result["status"] == "completed"

    @patch("src.learning.learning_processor.config")
    def test_no_corrections_found(self, mock_config):
        proc = _make_processor()
        mock_config.LEARNING_ENABLED = True
        mock_config.EMAIL_FETCH_DAYS = 7
        mock_config.CATEGORIES = [
            MagicMock(is_default=True, folder=""),
            MagicMock(is_default=False, folder="Suspicious"),
        ]
        mock_config.CATEGORIES[0].name = "regular"
        mock_config.CATEGORIES[1].name = "spam"
        mock_config.INBOX_FOLDER = "INBOX"
        proc.learning_generator.is_available.return_value = True

        # Email is in the expected folder (no correction)
        proc.db_manager.get_recent_classified_with_folders.return_value = [
            {"message_id": "<a@test>", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "X", "sender": "x@test.com"},
        ]

        with patch.object(proc, "_scan_all_folders", return_value={"<a@test>": "Suspicious"}):
            result = proc.reconcile_folders()

        assert result["status"] == "completed"
        assert result.get("corrections_found", 0) == 0

    @patch("src.learning.learning_processor.config")
    def test_correction_processed(self, mock_config):
        proc = _make_processor()
        mock_config.LEARNING_ENABLED = True
        mock_config.EMAIL_FETCH_DAYS = 7
        mock_config.LEARNING_RETENTION_DAYS = 0
        mock_config.CATEGORIES = [
            MagicMock(is_default=True, folder=""),
            MagicMock(is_default=False, folder="Suspicious"),
        ]
        mock_config.CATEGORIES[0].name = "regular"
        mock_config.CATEGORIES[1].name = "spam"
        mock_config.INBOX_FOLDER = "INBOX"
        mock_config.default_category.name = "regular"
        proc.learning_generator.is_available.return_value = True
        proc.learning_generator.generate_learning_summary.return_value = "LLM generated summary"
        proc.db_manager.save_learning_data.return_value = True
        proc.db_manager.get_recent_classified_with_folders.return_value = [
            {"message_id": "<a@test>", "email_id": "a1", "classification": "spam",
             "folder_moved_to": "Suspicious", "subject": "Not spam", "sender": "good@test.com"},
        ]

        with (
            patch.object(proc, "_scan_all_folders", return_value={"<a@test>": "INBOX"}),
            patch.object(proc, "_fetch_full_email", return_value={"id": "a1", "subject": "Not spam", "sender": "good@test.com", "body": "Hello", "date": "2026-01-01"}),
        ):
            result = proc.reconcile_folders()

        assert result["status"] == "completed"
        assert result["corrections_found"] == 1
        assert result["learning_generated"] == 1
        proc.db_manager.save_learning_data.assert_called_once()
        proc.db_manager.update_folder_moved_to.assert_called_once_with("<a@test>", None)

    @patch("src.learning.learning_processor.config")
    def test_correction_llm_failure_uses_template(self, mock_config):
        proc = _make_processor()
        mock_config.LEARNING_ENABLED = True
        mock_config.EMAIL_FETCH_DAYS = 7
        mock_config.LEARNING_RETENTION_DAYS = 0
        mock_config.CATEGORIES = [
            MagicMock(is_default=True, folder=""),
            MagicMock(is_default=False, folder="Newsletters"),
        ]
        mock_config.CATEGORIES[0].name = "regular"
        mock_config.CATEGORIES[1].name = "newsletter"
        mock_config.INBOX_FOLDER = "INBOX"
        mock_config.default_category.name = "regular"
        proc.learning_generator.is_available.return_value = True
        # LLM returns None (failure)
        proc.learning_generator.generate_learning_summary.return_value = None
        proc.db_manager.save_learning_data.return_value = True
        proc.db_manager.get_recent_classified_with_folders.return_value = [
            {"message_id": "<b@test>", "email_id": "b1", "classification": "newsletter",
             "folder_moved_to": "Newsletters", "subject": "Important", "sender": "boss@company.com"},
        ]

        with (
            patch.object(proc, "_scan_all_folders", return_value={"<b@test>": "INBOX"}),
            patch.object(proc, "_fetch_full_email", return_value={"id": "b1", "subject": "Important", "sender": "boss@company.com", "body": "Hi", "date": "2026-01-01"}),
        ):
            result = proc.reconcile_folders()

        assert result["status"] == "completed"
        assert result["learning_generated"] == 1

        # Verify the saved learning data uses template (contains key phrase)
        saved_data = proc.db_manager.save_learning_data.call_args[0][0]
        assert "was classified as newsletter" in saved_data.learning_summary
        assert "indicating it should be regular" in saved_data.learning_summary


# ---------------------------------------------------------------------------
# TestLearningType
# ---------------------------------------------------------------------------


class TestLearningType:
    """Verify learning_type determination in _process_single_correction."""

    @patch("src.learning.learning_processor.config")
    def test_false_positive_spam(self, mock_config):
        """Suspicious → INBOX means false_positive_spam."""
        proc = _make_processor()
        mock_config.default_category.name = "regular"
        mock_config.INBOX_FOLDER = "INBOX"
        proc.learning_generator.generate_learning_summary.return_value = "summary"
        proc.db_manager.save_learning_data.return_value = True
        proc._reset_stats()

        correction = {
            "message_id": "<a@test>", "email_id": "a1", "subject": "X",
            "sender": "x@test.com", "old_classification": "spam",
            "new_classification": "regular", "old_folder": "Suspicious", "new_folder": "INBOX",
        }

        with patch.object(proc, "_fetch_full_email", return_value={"id": "a1", "subject": "X", "sender": "x@test.com", "body": "Y", "date": "2026-01-01"}):
            proc._process_single_correction(correction)

        saved = proc.db_manager.save_learning_data.call_args[0][0]
        assert saved.learning_type == "false_positive_spam"

    @patch("src.learning.learning_processor.config")
    def test_false_negative_newsletter(self, mock_config):
        """INBOX → Newsletters means false_negative_newsletter."""
        proc = _make_processor()
        mock_config.default_category.name = "regular"
        mock_config.INBOX_FOLDER = "INBOX"
        proc.learning_generator.generate_learning_summary.return_value = "summary"
        proc.db_manager.save_learning_data.return_value = True
        proc._reset_stats()

        correction = {
            "message_id": "<a@test>", "email_id": "a1", "subject": "X",
            "sender": "x@test.com", "old_classification": "regular",
            "new_classification": "newsletter", "old_folder": "INBOX", "new_folder": "Newsletters",
        }

        with patch.object(proc, "_fetch_full_email", return_value={"id": "a1", "subject": "X", "sender": "x@test.com", "body": "Y", "date": "2026-01-01"}):
            proc._process_single_correction(correction)

        saved = proc.db_manager.save_learning_data.call_args[0][0]
        assert saved.learning_type == "false_negative_newsletter"

    @patch("src.learning.learning_processor.config")
    def test_cross_category(self, mock_config):
        """Newsletters → Suspicious means newsletter_to_spam."""
        proc = _make_processor()
        mock_config.default_category.name = "regular"
        mock_config.INBOX_FOLDER = "INBOX"
        proc.learning_generator.generate_learning_summary.return_value = "summary"
        proc.db_manager.save_learning_data.return_value = True
        proc._reset_stats()

        correction = {
            "message_id": "<a@test>", "email_id": "a1", "subject": "X",
            "sender": "x@test.com", "old_classification": "newsletter",
            "new_classification": "spam", "old_folder": "Newsletters", "new_folder": "Suspicious",
        }

        with patch.object(proc, "_fetch_full_email", return_value={"id": "a1", "subject": "X", "sender": "x@test.com", "body": "Y", "date": "2026-01-01"}):
            proc._process_single_correction(correction)

        saved = proc.db_manager.save_learning_data.call_args[0][0]
        assert saved.learning_type == "newsletter_to_spam"
