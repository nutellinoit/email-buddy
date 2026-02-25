"""Tests for EmailClient folder scanning and message lookup methods."""

from unittest.mock import MagicMock, patch


def _make_connected_client():
    """Create an EmailClient with a mocked IMAP connection."""
    mock_imap = MagicMock()
    mock_imap.noop.return_value = ("OK", [b""])
    mock_imap.select.return_value = ("OK", [b"42"])

    with patch("src.imap_ops.connect_ssl", return_value=mock_imap):
        from src.email_client import EmailClient

        client = EmailClient()
        client.connect()

    return client


# ---------------------------------------------------------------------------
# TestGetFolderMessageIds
# ---------------------------------------------------------------------------


class TestGetFolderMessageIds:
    """Tests for get_folder_message_ids() lightweight folder scanning."""

    def test_returns_message_ids(self):
        client = _make_connected_client()

        # Mock select + search + fetch sequence
        client.imap_client.select.return_value = ("OK", [b"10"])
        client.imap_client.noop.return_value = ("OK", [b""])
        client.imap_client.uid.side_effect = [
            # SEARCH result
            ("OK", [b"101 102"]),
            # FETCH for UID 101
            ("OK", [(b"101 (BODY[HEADER.FIELDS (MESSAGE-ID)] {30}", b"Message-ID: <a@test.com>\r\n"), b")"]),
            # FETCH for UID 102
            ("OK", [(b"102 (BODY[HEADER.FIELDS (MESSAGE-ID)] {30}", b"Message-ID: <b@test.com>\r\n"), b")"]),
        ]

        result = client.get_folder_message_ids("INBOX", since_days=7)

        assert "<a@test.com>" in result
        assert "<b@test.com>" in result
        assert result["<a@test.com>"] == "101"
        assert result["<b@test.com>"] == "102"

    def test_empty_folder(self):
        client = _make_connected_client()
        client.imap_client.select.return_value = ("OK", [b"0"])
        client.imap_client.noop.return_value = ("OK", [b""])
        client.imap_client.uid.return_value = ("OK", [b""])

        result = client.get_folder_message_ids("INBOX", since_days=7)
        assert result == {}

    def test_folder_selection_failure(self):
        client = _make_connected_client()
        client.imap_client.select.return_value = ("NO", [b"Folder not found"])
        client.imap_client.noop.return_value = ("OK", [b""])

        result = client.get_folder_message_ids("Nonexistent", since_days=7)
        assert result == {}


# ---------------------------------------------------------------------------
# TestFetchEmailByMessageId
# ---------------------------------------------------------------------------


class TestFetchEmailByMessageId:
    """Tests for fetch_email_by_message_id() full email retrieval."""

    def test_returns_none_when_not_found(self):
        client = _make_connected_client()
        client.imap_client.uid.return_value = ("OK", [b""])

        result = client.fetch_email_by_message_id("<nonexistent@test.com>")
        assert result is None

    def test_returns_none_when_disconnected(self):
        from src.email_client import EmailClient

        client = EmailClient()
        # Never connected
        result = client.fetch_email_by_message_id("<a@test.com>")
        assert result is None

    def test_returns_email_data_on_success(self):
        client = _make_connected_client()

        # First call: SEARCH by header -> returns UID
        # Second call: _fetch_email_data FETCH -> returns email content
        client.imap_client.uid.side_effect = [
            # SEARCH
            ("OK", [b"201"]),
            # FETCH (called by fetch_email_full)
            ("OK", [
                (b'201 (FLAGS (\\Seen) INTERNALDATE "01-Jan-2026 10:00:00 +0000" BODY[HEADER] {100}',
                 b"From: sender@test.com\r\nTo: recipient@test.com\r\nSubject: Test Subject\r\nDate: Mon, 1 Jan 2026 10:00:00 +0000\r\nMessage-ID: <found@test.com>\r\n"),
                (b" BODY[TEXT] {25}",
                 b"Hello, this is the body."),
                b")",
            ]),
        ]

        result = client.fetch_email_by_message_id("<found@test.com>")
        assert result is not None
        assert result["subject"] == "Test Subject"
        assert result["sender"] == "sender@test.com"
