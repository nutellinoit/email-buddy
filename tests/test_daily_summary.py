"""Tests for daily email summary generation."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.daily_summary import DailySummaryGenerator
from src.database import EmailDatabaseManager
from src.models import DailySummary, ProcessedEmail


@pytest.fixture
def file_db(tmp_path):
    """File-based SQLite DB (needed because :memory: creates a new DB per connection)."""
    db_path = str(tmp_path / "test.db")
    return EmailDatabaseManager(db_path)


@pytest.fixture
def generator(file_db):
    """Create a DailySummaryGenerator with the test DB."""
    gen = DailySummaryGenerator.__new__(DailySummaryGenerator)
    gen.db_manager = file_db
    return gen


def _make_processed_email(classification="regular", sender="user@example.com", subject="Test"):
    """Helper to create a ProcessedEmail for testing."""
    return ProcessedEmail(
        email_id=f"eid-{classification}-{subject}",
        message_id=f"<msg-{classification}@test>",
        subject=subject,
        sender=sender,
        date_received=datetime.now().isoformat(),
        classification=classification,
        confidence=0.9,
        reason="Test classification",
        folder_moved_to=None,
        processed_at=datetime.now().isoformat(),
        content_hash=f"hash-{classification}-{subject}",
    )


# ── Scheduling ──────────────────────────────────────────────────────


class TestIsSummaryDue:
    @patch("src.daily_summary.config")
    def test_disabled_returns_false(self, mock_config, generator):
        mock_config.DAILY_SUMMARY_ENABLED = False
        assert generator.is_summary_due() is False

    @patch("src.daily_summary.datetime")
    @patch("src.daily_summary.config")
    def test_before_configured_hour(self, mock_config, mock_dt, generator):
        mock_config.DAILY_SUMMARY_ENABLED = True
        mock_config.DAILY_SUMMARY_HOUR = 8
        mock_now = MagicMock()
        mock_now.hour = 7
        mock_dt.now.return_value = mock_now
        assert generator.is_summary_due() is False

    @patch("src.daily_summary.config")
    def test_due_after_hour_no_previous(self, mock_config, generator):
        mock_config.DAILY_SUMMARY_ENABLED = True
        mock_config.DAILY_SUMMARY_HOUR = 8
        with patch("src.daily_summary.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_dt.now.return_value = mock_now
            assert generator.is_summary_due() is True

    @patch("src.daily_summary.config")
    def test_not_due_if_already_sent_today(self, mock_config, generator):
        mock_config.DAILY_SUMMARY_ENABLED = True
        mock_config.DAILY_SUMMARY_HOUR = 8
        summary = DailySummary(
            generated_at=datetime.now().isoformat(),
            period_start=(datetime.now() - timedelta(hours=24)).isoformat(),
            period_end=datetime.now().isoformat(),
            total_processed=5,
            stats_json="{}",
            delivered=True,
        )
        generator.db_manager.save_daily_summary(summary)
        with patch("src.daily_summary.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 9
            mock_now.strftime = datetime.now().strftime
            mock_dt.now.return_value = mock_now
            assert generator.is_summary_due() is False


# ── Stats Context ──────────────────────────────────────────────────


class TestBuildStatsContext:
    def test_contains_totals_and_classifications(self, generator):
        stats = {
            "total_processed": 10,
            "by_classification": {"spam": 3, "regular": 7},
            "average_confidence": {"spam": 0.92, "regular": 0.85},
            "top_senders": {"alice@example.com": 5, "bob@example.com": 3},
            "learning_entries": 0,
        }
        since = datetime.now() - timedelta(hours=24)
        ctx = generator._build_stats_context(stats, since)
        assert ctx["total_processed"] == 10
        assert len(ctx["classifications"]) == 2
        assert any(c["name"] == "spam" and c["count"] == 3 for c in ctx["classifications"])
        assert len(ctx["senders"]) == 2

    def test_empty_stats(self, generator):
        stats = {
            "total_processed": 0,
            "by_classification": {},
            "average_confidence": {},
            "top_senders": {},
            "learning_entries": 0,
        }
        since = datetime.now() - timedelta(hours=24)
        ctx = generator._build_stats_context(stats, since)
        assert ctx["total_processed"] == 0
        assert ctx["classifications"] == []

    def test_learning_entries_preserved(self, generator):
        stats = {
            "total_processed": 5,
            "by_classification": {"regular": 5},
            "average_confidence": {"regular": 0.9},
            "top_senders": {},
            "learning_entries": 3,
        }
        since = datetime.now() - timedelta(hours=24)
        ctx = generator._build_stats_context(stats, since)
        assert ctx["learning_entries"] == 3


# ── Narrative Generation ────────────────────────────────────────────


class TestGenerateNarrative:
    @patch("src.daily_summary.config")
    @patch("src.daily_summary.llm_complete")
    @patch("src.daily_summary.is_llm_available")
    def test_returns_narrative_on_success(self, mock_available, mock_complete, mock_config, generator):
        mock_available.return_value = True
        mock_complete.return_value = "- Check your spam folder."
        mock_config.DAILY_SUMMARY_LANGUAGE = "English"
        stats = {"total_processed": 10, "by_classification": {"regular": 10}, "average_confidence": {}, "top_senders": {}, "learning_entries": 0}
        narrative = generator._generate_narrative(stats, [])
        assert narrative == "- Check your spam folder."
        mock_complete.assert_called_once()

    @patch("src.daily_summary.is_llm_available")
    def test_returns_none_when_llm_unavailable(self, mock_available, generator):
        mock_available.return_value = False
        stats = {"total_processed": 10, "by_classification": {}, "average_confidence": {}, "top_senders": {}, "learning_entries": 0}
        assert generator._generate_narrative(stats, []) is None

    @patch("src.daily_summary.config")
    @patch("src.daily_summary.llm_complete")
    @patch("src.daily_summary.is_llm_available")
    def test_returns_none_on_llm_error(self, mock_available, mock_complete, mock_config, generator):
        mock_available.return_value = True
        mock_complete.return_value = None
        mock_config.DAILY_SUMMARY_LANGUAGE = "English"
        stats = {"total_processed": 10, "by_classification": {}, "average_confidence": {}, "top_senders": {}, "learning_entries": 0}
        assert generator._generate_narrative(stats, []) is None

    @patch("src.daily_summary.config")
    @patch("src.daily_summary.llm_complete")
    @patch("src.daily_summary.is_llm_available")
    def test_includes_previous_summaries(self, mock_available, mock_complete, mock_config, generator):
        mock_available.return_value = True
        mock_complete.return_value = "- Spam increased."
        mock_config.DAILY_SUMMARY_LANGUAGE = "English"
        stats = {"total_processed": 10, "by_classification": {"spam": 5}, "average_confidence": {}, "top_senders": {}, "learning_entries": 0}
        prev = DailySummary(
            generated_at="2026-02-22T08:00:00",
            period_start="2026-02-21T08:00:00",
            period_end="2026-02-22T08:00:00",
            total_processed=8,
            stats_json=json.dumps({"total_processed": 8, "by_classification": {"spam": 2}}),
            delivered=True,
        )
        generator._generate_narrative(stats, [prev])
        call_args = mock_complete.call_args
        user_content = call_args[1]["messages"][0]["content"] if "messages" in call_args[1] else call_args[0][0][0]["content"]
        assert "2026-02-22" in user_content

    @patch("src.daily_summary.config")
    @patch("src.daily_summary.llm_complete")
    @patch("src.daily_summary.is_llm_available")
    def test_system_prompt_contains_language(self, mock_available, mock_complete, mock_config, generator):
        mock_available.return_value = True
        mock_complete.return_value = "- Tips here."
        mock_config.DAILY_SUMMARY_LANGUAGE = "Italian"
        stats = {"total_processed": 5, "by_classification": {}, "average_confidence": {}, "top_senders": {}, "learning_entries": 0}
        generator._generate_narrative(stats, [])
        call_args = mock_complete.call_args
        system_prompt = call_args[1].get("system_prompt", "")
        assert "Italian" in system_prompt

    @patch("src.daily_summary.config")
    @patch("src.daily_summary.llm_complete")
    @patch("src.daily_summary.is_llm_available")
    def test_narrative_includes_email_details(self, mock_available, mock_complete, mock_config, generator):
        mock_available.return_value = True
        mock_complete.return_value = "- Reply to Bob."
        mock_config.DAILY_SUMMARY_LANGUAGE = "English"
        stats = {"total_processed": 2, "by_classification": {"regular": 2}, "average_confidence": {}, "top_senders": {}, "learning_entries": 0}
        emails = [
            _make_processed_email(classification="regular", sender="bob@example.com", subject="Project Update"),
        ]
        generator._generate_narrative(stats, [], emails)
        call_args = mock_complete.call_args
        user_content = call_args[1]["messages"][0]["content"]
        assert "bob@example.com" in user_content
        assert "Project Update" in user_content


# ── HTML Rendering ──────────────────────────────────────────────────


class TestMarkdownToHtml:
    def test_empty_string(self, generator):
        assert generator._markdown_to_html("") == ""

    def test_whitespace_only(self, generator):
        assert generator._markdown_to_html("   \n  ") == ""

    def test_single_bullet(self, generator):
        result = generator._markdown_to_html("- Check your spam folder.")
        assert "<ul" in result
        assert "<li" in result
        assert "Check your spam folder." in result
        assert "</ul>" in result

    def test_multiple_bullets(self, generator):
        result = generator._markdown_to_html("- Item one\n- Item two\n- Item three")
        assert result.count("<li") == 3
        assert result.count("<ul") == 1

    def test_bold_text(self, generator):
        result = generator._markdown_to_html("- **Warning**: spam spike detected")
        assert "<strong>Warning</strong>" in result
        assert "<li" in result

    def test_multiple_bold_in_line(self, generator):
        result = generator._markdown_to_html("**A** and **B**")
        assert "<strong>A</strong>" in result
        assert "<strong>B</strong>" in result

    def test_plain_text_becomes_paragraph(self, generator):
        result = generator._markdown_to_html("Hello world")
        assert "<p" in result
        assert "Hello world" in result

    def test_mixed_paragraphs_and_bullets(self, generator):
        text = "Summary:\n- bullet one\n- bullet two\nConclusion."
        result = generator._markdown_to_html(text)
        assert "<p" in result
        assert "<ul" in result
        assert "<li" in result
        assert "Summary:" in result
        assert "Conclusion." in result


class TestRenderHtml:
    def test_html_with_narrative(self, generator):
        ctx = {
            "period_start": "2026-02-23 00:00",
            "period_end": "2026-02-23 08:00",
            "period_hours": 8.0,
            "total_processed": 10,
            "classifications": [{"name": "spam", "count": 3, "avg_confidence": 0.92}],
            "senders": [{"address": "alice@example.com", "count": 5}],
            "learning_entries": 0,
        }
        html = generator._render_html(ctx, "- Check the 3 spam emails from today.")
        assert "<!DOCTYPE html>" in html
        assert "10" in html
        assert "Your assistant" in html
        assert "Check the 3 spam emails" in html
        assert "Email-Buddy" in html
        assert "alice@example.com" in html
        assert "Spam" in html
        # Assistant section appears BEFORE stats
        assert html.index("Your assistant") < html.index("Total Emails Processed")
        # Markdown bullets converted to HTML list
        assert "<li" in html
        assert "<ul" in html

    def test_html_without_narrative(self, generator):
        ctx = {
            "period_start": "2026-02-23 00:00",
            "period_end": "2026-02-23 08:00",
            "period_hours": 8.0,
            "total_processed": 5,
            "classifications": [],
            "senders": [],
            "learning_entries": 0,
        }
        html = generator._render_html(ctx, None)
        assert "<!DOCTYPE html>" in html
        assert "Tips" not in html
        assert "Generated by Email-Buddy" in html

    def test_html_uses_table_layout(self, generator):
        ctx = {
            "period_start": "2026-02-23 00:00",
            "period_end": "2026-02-23 08:00",
            "period_hours": 8.0,
            "total_processed": 5,
            "classifications": [],
            "senders": [],
            "learning_entries": 0,
        }
        html = generator._render_html(ctx, None)
        assert '<table width="100%"' in html
        assert '<table width="600"' in html

    def test_learning_section_shown_when_entries(self, generator):
        ctx = {
            "period_start": "2026-02-23 00:00",
            "period_end": "2026-02-23 08:00",
            "period_hours": 8.0,
            "total_processed": 5,
            "classifications": [],
            "senders": [],
            "learning_entries": 3,
        }
        html = generator._render_html(ctx, None)
        assert "Learning Activity" in html
        assert "3" in html

    def test_learning_section_hidden_when_zero(self, generator):
        ctx = {
            "period_start": "2026-02-23 00:00",
            "period_end": "2026-02-23 08:00",
            "period_hours": 8.0,
            "total_processed": 5,
            "classifications": [],
            "senders": [],
            "learning_entries": 0,
        }
        html = generator._render_html(ctx, None)
        assert "Learning Activity" not in html


# ── IMAP Delivery ───────────────────────────────────────────────────


class TestDeliverToInbox:
    @patch("src.daily_summary.EmailClient")
    @patch("src.daily_summary.config")
    def test_append_called_correctly(self, mock_config, mock_client_cls, generator):
        mock_config.IMAP_USERNAME = "test@example.com"
        mock_config.INBOX_FOLDER = "INBOX"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.imap_client.append.return_value = ("OK", [b"Success"])
        mock_client_cls.return_value = mock_client

        result = generator._deliver_to_inbox("[Email-Buddy] Test", "<html>Test body</html>")
        assert result is True
        mock_client.imap_client.append.assert_called_once()
        call_args = mock_client.imap_client.append.call_args[0]
        assert call_args[0] == "INBOX"
        assert call_args[1] == ""  # No flags (unread)
        # Verify HTML content type
        message_bytes = call_args[3]
        assert b"Content-Type: text/html" in message_bytes
        mock_client.disconnect.assert_called_once()

    @patch("src.daily_summary.EmailClient")
    @patch("src.daily_summary.config")
    def test_returns_false_on_connection_failure(self, mock_config, mock_client_cls, generator):
        mock_config.IMAP_USERNAME = "test@example.com"
        mock_config.INBOX_FOLDER = "INBOX"

        mock_client = MagicMock()
        mock_client.connect.return_value = False
        mock_client_cls.return_value = mock_client

        result = generator._deliver_to_inbox("[Email-Buddy] Test", "<html>Test body</html>")
        assert result is False

    @patch("src.daily_summary.EmailClient")
    @patch("src.daily_summary.config")
    def test_returns_false_on_append_failure(self, mock_config, mock_client_cls, generator):
        mock_config.IMAP_USERNAME = "test@example.com"
        mock_config.INBOX_FOLDER = "INBOX"

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.imap_client.append.return_value = ("NO", [b"Append failed"])
        mock_client_cls.return_value = mock_client

        result = generator._deliver_to_inbox("[Email-Buddy] Test", "<html>Test body</html>")
        assert result is False
        mock_client.disconnect.assert_called_once()


# ── Summary Persistence (DB) ───────────────────────────────────────


class TestSummaryPersistence:
    def test_save_and_retrieve(self, file_db):
        summary = DailySummary(
            generated_at=datetime.now().isoformat(),
            period_start=(datetime.now() - timedelta(hours=24)).isoformat(),
            period_end=datetime.now().isoformat(),
            total_processed=15,
            stats_json=json.dumps({"total_processed": 15}),
            narrative="All good.",
            delivered=True,
        )
        assert file_db.save_daily_summary(summary) is True
        recent = file_db.get_recent_summaries(limit=1)
        assert len(recent) == 1
        assert recent[0].total_processed == 15
        assert recent[0].narrative == "All good."
        assert recent[0].delivered is True

    def test_is_summary_sent_today_true(self, file_db):
        summary = DailySummary(
            generated_at=datetime.now().isoformat(),
            period_start=(datetime.now() - timedelta(hours=24)).isoformat(),
            period_end=datetime.now().isoformat(),
            total_processed=5,
            stats_json="{}",
            delivered=True,
        )
        file_db.save_daily_summary(summary)
        assert file_db.is_summary_sent_today() is True

    def test_is_summary_sent_today_false_no_entries(self, file_db):
        assert file_db.is_summary_sent_today() is False

    def test_is_summary_sent_today_false_old_entry(self, file_db):
        summary = DailySummary(
            generated_at=(datetime.now() - timedelta(days=2)).isoformat(),
            period_start=(datetime.now() - timedelta(days=3)).isoformat(),
            period_end=(datetime.now() - timedelta(days=2)).isoformat(),
            total_processed=5,
            stats_json="{}",
            delivered=True,
        )
        file_db.save_daily_summary(summary)
        assert file_db.is_summary_sent_today() is False

    def test_get_recent_summaries_ordering(self, file_db):
        for i in range(3):
            summary = DailySummary(
                generated_at=(datetime.now() - timedelta(days=i)).isoformat(),
                period_start=(datetime.now() - timedelta(days=i + 1)).isoformat(),
                period_end=(datetime.now() - timedelta(days=i)).isoformat(),
                total_processed=i * 10,
                stats_json=json.dumps({"total_processed": i * 10}),
                delivered=True,
            )
            file_db.save_daily_summary(summary)
        recent = file_db.get_recent_summaries(limit=2)
        assert len(recent) == 2
        # Most recent first (by generated_at)
        assert recent[0].generated_at >= recent[1].generated_at


# ── Integration: generate_and_send ──────────────────────────────────


class TestGenerateAndSend:
    @patch("src.daily_summary.EmailClient")
    @patch("src.daily_summary.llm_complete")
    @patch("src.daily_summary.is_llm_available")
    @patch("src.daily_summary.config")
    def test_full_flow(self, mock_config, mock_available, mock_complete, mock_client_cls, generator):
        mock_config.DAILY_SUMMARY_ENABLED = True
        mock_config.DAILY_SUMMARY_HOUR = 8
        mock_config.DAILY_SUMMARY_LANGUAGE = "English"
        mock_config.IMAP_USERNAME = "test@example.com"
        mock_config.INBOX_FOLDER = "INBOX"
        mock_config.DATABASE_PATH = "/tmp/test.db"

        mock_available.return_value = True
        mock_complete.return_value = "- Normal day."

        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.imap_client.append.return_value = ("OK", [b"Done"])
        mock_client_cls.return_value = mock_client

        for i in range(3):
            generator.db_manager.save_processed_email(
                _make_processed_email(classification="regular", subject=f"Email {i}")
            )

        result = generator.generate_and_send()
        assert result is True

        summaries = generator.db_manager.get_recent_summaries(limit=1)
        assert len(summaries) == 1
        assert summaries[0].delivered is True
        assert summaries[0].total_processed == 3

    @patch("src.daily_summary.config")
    def test_skips_when_no_emails(self, mock_config, generator):
        mock_config.DAILY_SUMMARY_ENABLED = True
        mock_config.DATABASE_PATH = "/tmp/test.db"

        result = generator.generate_and_send()
        assert result is True

        summaries = generator.db_manager.get_recent_summaries(limit=1)
        assert len(summaries) == 1
        assert summaries[0].total_processed == 0
        assert summaries[0].delivered is False


# ── Database: get_summary_statistics_since ──────────────────────────


class TestGetSummaryStatisticsSince:
    def test_aggregates_correctly(self, file_db):
        for i, classification in enumerate(["spam", "spam", "regular", "newsletter"]):
            file_db.save_processed_email(
                _make_processed_email(
                    classification=classification,
                    subject=f"Email-{classification}-{i}",
                    sender=f"{classification}@example.com",
                )
            )
        since = datetime.now() - timedelta(hours=1)
        stats = file_db.get_summary_statistics_since(since)
        assert stats["total_processed"] == 4
        assert stats["by_classification"]["spam"] == 2
        assert stats["by_classification"]["regular"] == 1
        assert stats["by_classification"]["newsletter"] == 1
        assert len(stats["top_senders"]) >= 1

    def test_excludes_old_emails(self, file_db):
        file_db.save_processed_email(
            _make_processed_email(classification="regular", subject="Recent")
        )
        since = datetime.now() + timedelta(hours=1)
        stats = file_db.get_summary_statistics_since(since)
        assert stats["total_processed"] == 0
