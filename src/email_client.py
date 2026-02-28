"""
IMAP email client for connecting to email servers and managing emails.

Orchestration layer: manages connection lifecycle, folder resolution,
retry logic, and delegates raw IMAP operations to ``imap_ops``.
"""

import contextlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from . import imap_ops
from .config import config

logger = logging.getLogger(__name__)


class EmailClient:
    """IMAP email client for fetching and managing emails."""

    def __init__(self):
        self.imap_client = None
        self.connected = False
        self._connection_time = None
        self._operations_count = 0
        self._current_folder = None
        self._folder_separator: Optional[str] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to IMAP server."""
        try:
            logger.debug(
                f"Connecting to IMAP server {config.IMAP_HOST}:{config.IMAP_PORT}"
            )

            if config.IMAP_USE_SSL:
                self.imap_client = imap_ops.connect_ssl(
                    config.IMAP_HOST,
                    config.IMAP_PORT,
                    config.IMAP_USERNAME,
                    config.IMAP_PASSWORD,
                )
            else:
                self.imap_client = imap_ops.connect_plain(
                    config.IMAP_HOST,
                    config.IMAP_PORT,
                    config.IMAP_USERNAME,
                    config.IMAP_PASSWORD,
                )

            self.connected = True
            self._connection_time = datetime.now()
            self._operations_count = 0

            # Detect folder hierarchy separator if subfolder mode is enabled
            if config.CATEGORY_FOLDERS_UNDER_INBOX:
                self._folder_separator = imap_ops.detect_separator(
                    self.imap_client
                )

            logger.debug("Successfully connected to IMAP server")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            return False

    def disconnect(self):
        """Disconnect from IMAP server."""
        if self.imap_client and self.connected:
            try:
                imap_ops.disconnect(self.imap_client)
                logger.debug("Disconnected from IMAP server")
            except Exception as e:
                logger.error(f"Error disconnecting from IMAP server: {e}")
            finally:
                self.connected = False
                self.imap_client = None
                self._connection_time = None
                self._operations_count = 0
                self._current_folder = None

    def is_connection_alive(self) -> bool:
        """Check if the IMAP connection is still alive."""
        if not self.connected:
            return False
        return imap_ops.is_alive(self.imap_client)

    def ensure_connection(self) -> bool:
        """Ensure we have a valid IMAP connection, reconnecting if necessary."""
        if self.is_connection_alive():
            return True

        logger.debug("IMAP connection is stale, reconnecting...")

        # Clean up stale connection
        self.connected = False
        if self.imap_client:
            with contextlib.suppress(Exception):
                imap_ops.disconnect(self.imap_client)
            self.imap_client = None
        self._connection_time = None
        self._operations_count = 0
        self._current_folder = None

        # Reconnect
        return self.connect()

    def should_refresh_connection(self) -> bool:
        """Check if connection should be refreshed based on age and operations."""
        if not self.connected or not self._connection_time:
            return False

        # Refresh if connection is older than 5 minutes
        connection_age = (
            datetime.now() - self._connection_time
        ).total_seconds()
        if connection_age > 300:  # 5 minutes
            logger.debug(
                f"Connection is {connection_age:.0f} seconds old, should refresh"
            )
            return True

        # Refresh if we've done many operations
        if self._operations_count > 50:
            logger.debug(
                f"Performed {self._operations_count} operations, should refresh"
            )
            return True

        return False

    def refresh_connection_if_needed(self) -> bool:
        """Refresh connection if it's getting stale."""
        if self.should_refresh_connection():
            logger.debug("Refreshing IMAP connection proactively")
            current_folder = self._current_folder

            # Disconnect and reconnect
            self.disconnect()
            if not self.connect():
                return False

            # Re-select folder if we had one
            if current_folder:
                return self.select_folder(current_folder)

        return True

    # ------------------------------------------------------------------
    # Folder resolution
    # ------------------------------------------------------------------

    def _resolve_folder(self, folder: str) -> str:
        """Resolve a logical folder name to the full IMAP path.

        When CATEGORY_FOLDERS_UNDER_INBOX is enabled, prepends INBOX + separator.
        Idempotent: already-resolved names are returned as-is.
        """
        if (
            not config.CATEGORY_FOLDERS_UNDER_INBOX
            or not self._folder_separator
        ):
            return folder
        if folder == config.INBOX_FOLDER:
            return folder
        if folder.startswith(
            f"{config.INBOX_FOLDER}{self._folder_separator}"
        ):
            return folder
        return f"{config.INBOX_FOLDER}{self._folder_separator}{folder}"

    # ------------------------------------------------------------------
    # Folder operations
    # ------------------------------------------------------------------

    def select_folder(self, folder_name: str) -> bool:
        """Select a folder/mailbox."""
        folder_name = self._resolve_folder(folder_name)
        if not self.ensure_connection():
            logger.error("Cannot select folder - no IMAP connection")
            return False

        try:
            if not imap_ops.select_folder(self.imap_client, folder_name):
                return False

            # Track current folder
            self._current_folder = folder_name
            self._operations_count += 1
            logger.debug(f"Selected folder: {folder_name}")
            return True

        except Exception as e:
            logger.error(f"Error selecting folder {folder_name}: {e}")
            return False

    def create_folder(self, folder_name: str) -> bool:
        """Create a folder if it doesn't exist."""
        folder_name = self._resolve_folder(folder_name)
        if not self.ensure_connection():
            logger.error("Cannot create folder - no IMAP connection")
            return False

        try:
            logger.info(f"Creating folder '{folder_name}'...")
            return imap_ops.create_folder(self.imap_client, folder_name)

        except Exception as e:
            logger.error(f"Error creating folder {folder_name}: {e}")
            return False

    def folder_exists(self, folder_name: str) -> bool:
        """Check if a folder exists using LIST command."""
        folder_name = self._resolve_folder(folder_name)
        if not self.ensure_connection():
            logger.error("Cannot check folder existence - no IMAP connection")
            return False

        try:
            logger.debug(f"Checking if folder '{folder_name}' exists using LIST command")
            exists = imap_ops.folder_exists(self.imap_client, folder_name)
            logger.debug(
                f"Folder '{folder_name}' {'exists' if exists else 'does not exist'}"
            )
            return exists

        except Exception as e:
            logger.error(f"Error checking folder existence {folder_name}: {e}")
            return False

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def fetch_emails(self, limit: int = 5, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Fetch recent emails from the current folder with offset support.

        Args:
            limit: Maximum number of emails to fetch
            offset: Number of emails to skip from the end (for pagination)

        Returns:
            List of email data dictionaries
        """
        if not self.connected:
            logger.error("Not connected to IMAP server")
            return []

        try:
            # Search for all emails using UID (unique identifiers)
            result = self.imap_client.uid("search", None, "ALL")
            if result[0] != "OK":
                logger.error(f"Failed to search emails: {result[1]}")
                return []

            email_ids = result[1][0].split()
            if not email_ids:
                logger.debug("No emails found in current folder")
                return []

            # Calculate slice indices for recent emails with offset
            total_emails = len(email_ids)
            start_idx = max(0, total_emails - limit - offset)
            end_idx = max(0, total_emails - offset)

            # Get emails in the specified range (most recent first)
            selected_ids = (
                email_ids[start_idx:end_idx] if start_idx < end_idx else []
            )

            # Refresh connection if needed before fetching emails
            self.refresh_connection_if_needed()

            emails = []
            for email_id in selected_ids:
                email_data = imap_ops.fetch_email_full(
                    self.imap_client, email_id
                )
                if email_data:
                    emails.append(email_data)

            logger.debug(
                f"Fetched {len(emails)} emails (limit={limit}, offset={offset})"
            )
            return emails

        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return []

    def get_next_unprocessed_email(self, db_manager) -> Optional[Dict[str, Any]]:
        """Get the next unprocessed email using optimized approach with SEARCH SINCE."""
        try:
            if not self.connected:
                logger.error("Not connected to IMAP server")
                return None

            # Calculate date for SINCE search
            from datetime import timedelta

            fetch_days = config.EMAIL_FETCH_DAYS
            since_date = (
                datetime.now() - timedelta(days=fetch_days)
            ).strftime("%d-%b-%Y")

            # Search for emails from the configured range
            logger.debug(f"Searching for emails since {since_date}")
            email_ids = imap_ops.search_since(
                self.imap_client, since_date
            )
            if not email_ids:
                logger.debug(
                    f"No emails found in the last {fetch_days} days"
                )
                return None

            logger.info(
                f"Found {len(email_ids)} emails from the last {fetch_days} days to check"
            )

            # Process emails from newest to oldest to handle recent emails first
            for email_id in reversed(email_ids):
                # First fetch headers only for quick checking
                header_data = imap_ops.fetch_headers_only(
                    self.imap_client, email_id
                )
                if not header_data:
                    continue

                # Skip self-generated emails (daily summaries injected via IMAP APPEND)
                sender = header_data.get("sender", "")
                if sender and "noreply@email-buddy" in sender:
                    logger.debug(
                        f"Skipping self-generated email: {header_data.get('subject', '')[:50]}"
                    )
                    continue

                # Check if already processed using database (with header data only)
                if not db_manager.is_email_processed(header_data):
                    # Now fetch the full email since it's unprocessed
                    logger.debug(
                        f"Found unprocessed email: {header_data.get('subject', 'No Subject')[:50]}..."
                    )
                    email_data = imap_ops.fetch_email_full(
                        self.imap_client, email_id
                    )
                    if email_data:
                        return email_data
                    else:
                        logger.warning(
                            f"Failed to fetch full content for unprocessed email UID {email_id}"
                        )
                else:
                    logger.debug(
                        f"Skipping processed email: {header_data.get('content_id', 'unknown')[:8]}..."
                    )

            logger.info(f"All {len(email_ids)} emails already processed")
            return None

        except Exception as e:
            logger.error(f"Error getting next unprocessed email: {e}")
            return None

    def fetch_email_by_message_id(
        self, message_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a full email by its Message-ID header in the current folder."""
        try:
            if not self.connected:
                logger.error("Not connected to IMAP server")
                return None

            uid_list = imap_ops.search_by_message_id(
                self.imap_client, message_id
            )
            if not uid_list:
                return None

            return imap_ops.fetch_email_full(
                self.imap_client, uid_list[0]
            )

        except Exception as e:
            logger.error(
                f"Error fetching email by message_id {message_id}: {e}"
            )
            return None

    def get_folder_message_ids(
        self, folder: str, since_days: int
    ) -> Dict[str, str]:
        """Get {message_id: imap_uid} for recent emails in a folder.

        Lightweight scan: only fetches the Message-ID header per email.
        """
        folder = self._resolve_folder(folder)
        if not self.select_folder(folder):
            logger.error(f"Cannot scan folder {folder}")
            return {}

        try:
            from datetime import timedelta

            since_date = (
                datetime.now() - timedelta(days=since_days)
            ).strftime("%d-%b-%Y")
            email_ids = imap_ops.search_since(
                self.imap_client, since_date
            )
            if not email_ids:
                return {}

            message_ids: Dict[str, str] = {}
            for uid in email_ids:
                mid = imap_ops.fetch_message_id_header(
                    self.imap_client, uid
                )
                if mid:
                    message_ids[mid] = (
                        uid.decode() if isinstance(uid, bytes) else str(uid)
                    )

            logger.debug(
                f"Folder {folder}: found {len(message_ids)} message_ids "
                f"from last {since_days} days"
            )
            return message_ids

        except Exception as e:
            logger.error(
                f"Error scanning folder {folder} for message_ids: {e}"
            )
            return {}

    # ------------------------------------------------------------------
    # Move / Flags
    # ------------------------------------------------------------------

    def move_email(self, email_identifier, destination_folder: str) -> bool:
        """Move email to a different folder with flag preservation using atomic operations."""
        destination_folder = self._resolve_folder(destination_folder)
        # Extract IMAP UID from email data or use directly if it's a UID string
        if isinstance(email_identifier, dict):
            # Email data dictionary - extract IMAP UID
            imap_uid = email_identifier.get("imap_uid")
            if not imap_uid:
                # Fallback to old 'id' field for backward compatibility
                imap_uid = email_identifier.get("id")
            content_id = email_identifier.get("content_id", "unknown")
            email_flags = email_identifier.get("flags", [])
            raw_message = email_identifier.get("raw_message")
            internaldate = email_identifier.get("internaldate")
        else:
            # Assume it's a UID string (backward compatibility)
            imap_uid = str(email_identifier)
            content_id = "legacy"
            email_flags = []
            raw_message = None
            internaldate = None

        if not imap_uid:
            logger.error(f"No IMAP UID found for email {content_id}")
            return False

        return self._atomic_move_with_flags(
            email_identifier,
            imap_uid,
            destination_folder,
            content_id,
            email_flags,
            raw_message,
            internaldate,
            max_retries=3,
        )

    def mark_as_read(
        self,
        email_identifier: Union[Dict[str, Any], str],
        folder: Optional[str] = None,
    ) -> bool:
        """
        Mark an email as read by setting the \\Seen flag.

        Args:
            email_identifier: Either email_data dict or IMAP UID string
            folder: Optional folder name to select before marking (if None, uses current folder)

        Returns:
            bool: True if marked successfully, False otherwise
        """
        try:
            if not self.ensure_connection():
                logger.error("Cannot mark email as read - no connection")
                return False

            # Extract IMAP UID
            if isinstance(email_identifier, dict):
                imap_uid = email_identifier.get("imap_uid")
                content_id = email_identifier.get("content_id", "unknown")
            else:
                imap_uid = email_identifier
                content_id = imap_uid

            if not imap_uid:
                logger.error(f"No IMAP UID found for email {content_id}")
                return False

            success = imap_ops.mark_as_read(
                self.imap_client, imap_uid, folder
            )
            if success:
                logger.debug(
                    f"Marked email {content_id[:8] if len(content_id) > 8 else content_id}... "
                    f"as read in folder {folder or 'current'}"
                )
            else:
                logger.error(
                    f"Failed to mark email "
                    f"{content_id[:8] if len(content_id) > 8 else content_id}... as read"
                )
            return success

        except Exception as e:
            logger.error(f"Error marking email as read: {e}")
            return False

    def get_fresh_uid_by_content(
        self, email_data: Dict[str, Any]
    ) -> Optional[str]:
        """Get fresh IMAP UID by searching for email content."""
        try:
            if not self.ensure_connection():
                return None

            # Search by message ID if available
            message_id = email_data.get("message_id", "")
            if message_id:
                uid_list = imap_ops.search_by_message_id(
                    self.imap_client, message_id
                )
                if uid_list:
                    fresh_uid = uid_list[0].decode()
                    logger.debug(
                        f"Found fresh UID {fresh_uid} for message_id {message_id}"
                    )
                    return fresh_uid

            # Fallback: search by subject and sender
            subject = email_data.get("subject", "")
            sender = email_data.get("sender", "")
            if subject and sender:
                uid_list = imap_ops.search_by_subject_sender(
                    self.imap_client, subject, sender
                )
                if uid_list:
                    fresh_uid = uid_list[0].decode()
                    logger.debug(
                        f"Found fresh UID {fresh_uid} by subject/sender search"
                    )
                    return fresh_uid

            logger.debug(
                f"Could not find fresh UID for email "
                f"{email_data.get('content_id', 'unknown')}"
            )
            return None

        except Exception as e:
            logger.error(f"Error getting fresh UID: {e}")
            return None

    def verify_uid_exists(self, uid: str) -> bool:
        """Verify if a UID still exists in the current folder."""
        return imap_ops.uid_exists(self.imap_client, uid)

    def _atomic_move_with_flags(
        self,
        email_data,
        imap_uid: str,
        destination_folder: str,
        content_id: str = "unknown",
        email_flags: Optional[list] = None,
        raw_message=None,
        internaldate: Optional[str] = None,
        max_retries: int = 3,
    ) -> bool:
        """Move email using atomic operations with flag preservation."""
        if email_flags is None:
            email_flags = []

        for attempt in range(max_retries + 1):
            if not self.ensure_connection():
                logger.error(
                    f"Cannot move email {content_id} (UID {imap_uid}) "
                    f"- no IMAP connection (attempt {attempt + 1})"
                )
                if attempt < max_retries:
                    continue
                return False

            try:
                # Always try to get fresh UID for retry attempts
                if (
                    attempt > 0
                    and isinstance(email_data, dict)
                    and email_data
                ):
                    logger.debug(
                        f"Attempt {attempt + 1}: Getting fresh UID for email {content_id}"
                    )
                    fresh_uid = self.get_fresh_uid_by_content(email_data)
                    if fresh_uid and fresh_uid != imap_uid:
                        imap_uid = fresh_uid
                        logger.debug(
                            f"Using fresh UID {imap_uid} for email {content_id} "
                            f"(attempt {attempt + 1})"
                        )

                logger.debug(
                    f"Starting atomic move of email {content_id} "
                    f"(UID {imap_uid}) to folder '{destination_folder}' "
                    f"(attempt {attempt + 1})"
                )

                # Ensure destination folder exists
                if not self.folder_exists(destination_folder):
                    logger.debug(
                        f"Folder '{destination_folder}' doesn't exist, creating it..."
                    )
                    if not self.create_folder(destination_folder):
                        logger.error(
                            f"Failed to create folder '{destination_folder}'"
                        )
                        if attempt < max_retries:
                            continue
                        return False

                # Method 1: Try APPEND with original flags and INTERNALDATE (most reliable)
                if raw_message and email_flags:
                    success = imap_ops.move_using_append(
                        self.imap_client,
                        imap_uid,
                        destination_folder,
                        email_flags,
                        raw_message,
                        internaldate,
                    )
                    if success:
                        self._operations_count += 3  # append, store, expunge
                        logger.debug(
                            f"Successfully moved email {content_id} using APPEND method"
                        )
                        return True
                    else:
                        logger.debug(
                            f"APPEND method failed for email {content_id}, "
                            f"trying COPY method"
                        )

                # Method 2: Fallback to COPY with flag restoration
                success = imap_ops.move_using_copy(
                    self.imap_client, imap_uid, destination_folder
                )
                if success:
                    self._operations_count += 4  # copy, store flags, store deleted, expunge
                    logger.debug(
                        f"Successfully moved email {content_id} using COPY method"
                    )
                    return True

                # If we get here, both methods failed
                if attempt < max_retries:
                    logger.debug(
                        f"Both APPEND and COPY methods failed for email {content_id}, "
                        f"retrying (attempt {attempt + 1})"
                    )
                    continue
                else:
                    logger.error(
                        f"All move methods failed for email {content_id}"
                    )
                    return False

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Error in atomic move for email {content_id} "
                    f"(UID {imap_uid}): {error_msg}"
                )

                # Check for UID-related errors that require fresh UID lookup
                if any(
                    err in error_msg.lower()
                    for err in [
                        "invalid messageset",
                        "no such message",
                        "expunged",
                    ]
                ):
                    if attempt < max_retries:
                        logger.debug(
                            f"UID-related error in atomic move, will retry "
                            f"with fresh UID lookup (attempt {attempt + 1})"
                        )
                        continue
                elif any(
                    err in error_msg.lower()
                    for err in ["socket", "eof", "connection"]
                ) and attempt < max_retries:
                    logger.debug(
                        f"Connection error detected in atomic move, "
                        f"retrying (attempt {attempt + 1})"
                    )
                    continue
                return False

        logger.error(
            f"Failed to move email {content_id} (UID {imap_uid}) "
            f"after {max_retries + 1} attempts"
        )
        return False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        """Context manager entry."""
        if self.connect():
            return self
        else:
            raise ConnectionError("Failed to connect to IMAP server")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
