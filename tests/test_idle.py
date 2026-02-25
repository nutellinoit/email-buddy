"""Tests for IMAP IDLE watcher."""

from unittest.mock import MagicMock, patch

from src.idle_watcher import IMAPIdleWatcher


def _make_mock_imap():
    """Create a mock IMAP4_SSL instance with IDLE-ready state."""
    imap = MagicMock()
    imap.login.return_value = ("OK", [b"Logged in"])
    imap.select.return_value = ("OK", [b"42"])
    imap.capability.return_value = ("OK", [b"IMAP4rev1 IDLE UIDPLUS"])
    imap._command.return_value = b"TAG1"
    imap.readline.return_value = b"+ idling\r\n"
    imap._command_complete.return_value = ("OK", [None])
    imap.logout.return_value = ("BYE", [b"Logging out"])

    # Socket mock (SSL socket with pending())
    mock_sock = MagicMock()
    mock_sock.pending.return_value = 0
    mock_sock.fileno.return_value = 5
    imap.socket.return_value = mock_sock

    return imap


class TestIdleNewMail:
    """IDLE detects new mail and returns True."""

    @patch("src.idle_watcher.select.select")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_true_on_socket_data(self, mock_imap_class, mock_select):
        mock_imap = _make_mock_imap()
        mock_imap_class.return_value = mock_imap
        mock_select.return_value = ([mock_imap.socket()], [], [])

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=120)

        assert result is True
        mock_imap.send.assert_called_with(b"DONE\r\n")

    @patch("src.idle_watcher.select.select")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_true_on_ssl_pending(self, mock_imap_class, mock_select):
        """SSL buffered data detected without select()."""
        mock_imap = _make_mock_imap()
        mock_imap_class.return_value = mock_imap
        mock_imap.socket().pending.return_value = 42

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=120)

        assert result is True
        mock_select.assert_not_called()


class TestIdleTimeout:
    """IDLE times out and returns False."""

    @patch("src.idle_watcher.select.select")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_false_on_timeout(self, mock_imap_class, mock_select):
        mock_imap = _make_mock_imap()
        mock_imap_class.return_value = mock_imap
        mock_select.return_value = ([], [], [])

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=120)

        assert result is False


class TestIdleFallback:
    """Graceful fallback on errors."""

    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_false_on_connection_failure(self, mock_imap_class):
        mock_imap_class.side_effect = ConnectionRefusedError("refused")

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=60)

        assert result is False

    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_false_on_login_failure(self, mock_imap_class):
        mock_imap = _make_mock_imap()
        mock_imap.login.return_value = ("NO", [b"Bad credentials"])
        mock_imap_class.return_value = mock_imap

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=60)

        assert result is False

    @patch("src.idle_watcher.time.sleep")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_falls_back_to_sleep_when_idle_not_supported(self, mock_imap_class, mock_sleep):
        mock_imap = _make_mock_imap()
        mock_imap.capability.return_value = ("OK", [b"IMAP4rev1 UIDPLUS"])
        mock_imap_class.return_value = mock_imap

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=60)

        assert result is False
        mock_sleep.assert_called_once_with(60)

    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_false_on_idle_rejected(self, mock_imap_class):
        """Server rejects IDLE command (no '+' continuation)."""
        mock_imap = _make_mock_imap()
        mock_imap.readline.return_value = b"TAG1 BAD Unknown command\r\n"
        mock_imap_class.return_value = mock_imap

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=60)

        assert result is False

    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_returns_false_on_select_failure(self, mock_imap_class):
        mock_imap = _make_mock_imap()
        mock_imap.select.return_value = ("NO", [b"Folder not found"])
        mock_imap_class.return_value = mock_imap

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=60)

        assert result is False


class TestIdleChunking:
    """IDLE re-issues after 28-minute chunks for long timeouts."""

    @patch("src.idle_watcher.select.select")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_reissues_idle_for_long_timeout(self, mock_imap_class, mock_select):
        """Timeout of 3600s should issue IDLE 3 times (1680+1680+240)."""
        mock_imap = _make_mock_imap()
        mock_imap_class.return_value = mock_imap
        mock_select.return_value = ([], [], [])  # always timeout

        watcher = IMAPIdleWatcher()
        result = watcher.wait_for_changes(timeout=3600)

        assert result is False
        # ceil(3600/1680) = 3 IDLE commands
        assert mock_imap._command.call_count == 3


class TestIdleDisconnectOnCleanup:
    """Always disconnects, even on error."""

    @patch("src.idle_watcher.select.select")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_disconnects_after_success(self, mock_imap_class, mock_select):
        mock_imap = _make_mock_imap()
        mock_imap_class.return_value = mock_imap
        mock_select.return_value = ([mock_imap.socket()], [], [])

        watcher = IMAPIdleWatcher()
        watcher.wait_for_changes(timeout=120)

        mock_imap.logout.assert_called_once()

    @patch("src.idle_watcher.select.select")
    @patch("src.idle_watcher.imaplib.IMAP4_SSL")
    def test_disconnects_after_timeout(self, mock_imap_class, mock_select):
        mock_imap = _make_mock_imap()
        mock_imap_class.return_value = mock_imap
        mock_select.return_value = ([], [], [])

        watcher = IMAPIdleWatcher()
        watcher.wait_for_changes(timeout=120)

        mock_imap.logout.assert_called_once()
