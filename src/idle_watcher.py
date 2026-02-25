"""
IMAP IDLE watcher for real-time new-email notifications (RFC 2177).

Uses a dedicated IMAP connection to IDLE on INBOX. This connection is
separate from the processing connections used by EmailClient.
"""

import contextlib
import imaplib
import logging
import select
import ssl
import time
from typing import Optional

from .config import config

logger = logging.getLogger(__name__)

# RFC 2177 recommends re-issuing IDLE every 29 minutes.
# We use 28 minutes as a safety margin.
_MAX_IDLE_SECONDS = 28 * 60

# Register IDLE as a valid command in imaplib.
# IDLE is only valid in SELECTED state (after SELECT/EXAMINE).
if "IDLE" not in imaplib.Commands:
    imaplib.Commands["IDLE"] = ("SELECTED",)


class IMAPIdleWatcher:
    """Watch INBOX for new mail using IMAP IDLE.

    Each call to wait_for_changes() creates a fresh IMAP connection,
    enters IDLE, waits for a notification or timeout, then disconnects.

    If anything goes wrong (server doesn't support IDLE, connection drops,
    SSL error, etc.), the method returns False -- the caller treats this
    identically to a timeout and proceeds with normal processing.
    """

    def wait_for_changes(self, timeout: int) -> bool:
        """Block until new mail arrives or timeout expires.

        Args:
            timeout: Maximum seconds to wait (typically PROCESS_INTERVAL).

        Returns:
            True  -- IDLE detected new mail (EXISTS response).
            False -- Timeout expired or an error occurred.
        """
        imap: Optional[imaplib.IMAP4] = None
        try:
            imap = self._connect()
            if imap is None:
                return False

            if not self._select_inbox(imap):
                return False

            # Check if server advertises IDLE capability
            if not self._server_supports_idle(imap):
                logger.warning("IMAP server does not advertise IDLE capability, falling back to sleep")
                self._disconnect(imap)
                imap = None
                time.sleep(timeout)
                return False

            # IDLE loop: break total timeout into chunks of _MAX_IDLE_SECONDS
            # to comply with RFC 2177's 29-minute recommendation.
            remaining = timeout
            while remaining > 0:
                chunk = min(remaining, _MAX_IDLE_SECONDS)

                tag = self._enter_idle(imap)
                if tag is None:
                    return False

                got_data = self._wait_on_socket(imap, chunk)

                if not self._exit_idle(imap, tag):
                    # Failed to cleanly exit IDLE -- connection is unusable
                    return False

                if got_data:
                    logger.info("IDLE notification received -- new mail likely")
                    return True

                remaining -= chunk
                if remaining > 0:
                    logger.debug("IDLE chunk expired (%ds), re-issuing IDLE (%ds remaining)", chunk, remaining)

            # Total timeout expired with no notification
            return False

        except Exception:
            logger.warning("IDLE watcher error, falling back to timeout", exc_info=True)
            return False
        finally:
            if imap is not None:
                self._disconnect(imap)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect(self) -> Optional[imaplib.IMAP4]:
        """Create a fresh IMAP connection and log in."""
        try:
            if config.IMAP_USE_SSL:
                context = ssl.create_default_context()
                imap = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT, ssl_context=context)
            else:
                imap = imaplib.IMAP4(config.IMAP_HOST, config.IMAP_PORT)

            result = imap.login(config.IMAP_USERNAME, config.IMAP_PASSWORD)
            if result[0] != "OK":
                logger.error("IDLE watcher login failed: %s", result[1])
                return None

            logger.debug("IDLE watcher connected to %s", config.IMAP_HOST)
            return imap

        except Exception:
            logger.warning("IDLE watcher connection failed", exc_info=True)
            return None

    def _select_inbox(self, imap: imaplib.IMAP4) -> bool:
        """Select the INBOX folder."""
        try:
            result = imap.select(config.INBOX_FOLDER)
            if result[0] != "OK":
                logger.error("IDLE watcher failed to select %s: %s", config.INBOX_FOLDER, result[1])
                return False
            return True
        except Exception:
            logger.warning("IDLE watcher folder selection failed", exc_info=True)
            return False

    def _server_supports_idle(self, imap: imaplib.IMAP4) -> bool:
        """Check CAPABILITY response for IDLE support."""
        try:
            typ, data = imap.capability()
            if typ != "OK" or not data or not data[0]:
                return False
            caps = data[0]
            if isinstance(caps, bytes):
                return b"IDLE" in caps.upper()
            return "IDLE" in str(caps).upper()
        except Exception:
            logger.debug("Could not check IDLE capability", exc_info=True)
            # Optimistic: try IDLE anyway; _enter_idle will fail if unsupported
            return True

    def _enter_idle(self, imap: imaplib.IMAP4) -> Optional[bytes]:
        """Send IDLE command, consume the continuation response.

        Returns the command tag, or None on failure.
        """
        try:
            tag = imap._command("IDLE")
            # Server should respond with "+ idling" (continuation)
            resp = imap.readline()
            if not resp.startswith(b"+"):
                logger.error("IDLE rejected by server: %s", resp.strip())
                return None
            logger.debug("Entered IDLE (tag=%s)", tag)
            return tag
        except Exception:
            logger.warning("Failed to enter IDLE", exc_info=True)
            return None

    def _wait_on_socket(self, imap: imaplib.IMAP4, timeout: int) -> bool:
        """Wait for data on the IMAP socket using select().

        Returns True if data arrived, False on timeout.
        Handles SSL sockets correctly by checking pending() first.
        """
        sock = imap.socket()

        # SSL sockets may have buffered data that select() cannot see.
        if hasattr(sock, "pending") and sock.pending() > 0:
            return True

        readable, _, _ = select.select([sock], [], [], timeout)
        return bool(readable)

    def _exit_idle(self, imap: imaplib.IMAP4, tag: bytes) -> bool:
        """Send DONE to exit IDLE and read the tagged response.

        Returns True if IDLE exited cleanly, False on error.
        """
        try:
            imap.send(b"DONE\r\n")
            typ, _data = imap._command_complete("IDLE", tag)
            logger.debug("Exited IDLE: %s", typ)
            return typ == "OK"
        except Exception:
            logger.warning("Failed to exit IDLE cleanly", exc_info=True)
            return False

    def _disconnect(self, imap: imaplib.IMAP4) -> None:
        """Log out and close the IMAP connection."""
        with contextlib.suppress(Exception):
            imap.logout()
