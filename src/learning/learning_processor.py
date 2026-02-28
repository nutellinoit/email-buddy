"""
Learning processor that detects user corrections by reconciling folder contents.
"""

import contextlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import config
from ..database import get_database_manager
from ..email_client import EmailClient
from ..models import LearningData
from .learning_generator import LearningGenerator

logger = logging.getLogger(__name__)


class LearningProcessor:
    """Detects user corrections by comparing email folder locations with DB records."""

    def __init__(self):
        self.email_client = EmailClient()
        self.learning_generator = LearningGenerator()
        self.db_manager = get_database_manager()
        self.stats: Dict[str, Any] = {}

    def reconcile_folders(self) -> Dict[str, Any]:
        """
        Main workflow: scan category folders and detect user corrections.

        Compares where the system placed each email (DB) with where it is now (IMAP).
        Any discrepancy means the user moved the email → generate learning.

        Returns:
            Dictionary with processing statistics
        """
        if not config.LEARNING_ENABLED:
            logger.info("Learning system disabled, skipping folder reconciliation")
            return self._get_stats("disabled", "Learning system is disabled")

        logger.debug("Starting folder reconciliation...")
        self._reset_stats()

        try:
            # Check if LLM is available for generating summaries
            if not self.learning_generator.is_available():
                logger.warning("LLM not available, skipping folder reconciliation")
                return self._get_stats("skipped", "LLM not available")

            # Build folder ↔ classification maps from config
            folder_to_class, _class_to_folder = self._build_folder_maps()

            # Scan all category folders for message_ids (lightweight, headers only)
            all_folder_emails = self._scan_all_folders(folder_to_class, config.EMAIL_FETCH_DAYS)
            if all_folder_emails is None:
                return self._get_stats("error", "Failed to scan folders")

            # Get recent processed emails from DB
            recent_emails = self.db_manager.get_recent_classified_with_folders(config.EMAIL_FETCH_DAYS)
            if not recent_emails:
                logger.debug("No recent processed emails to reconcile")
                return self._get_stats("completed", "No emails to reconcile")

            # Find corrections: expected folder ≠ actual folder
            corrections = self._find_corrections(recent_emails, all_folder_emails, folder_to_class)

            if not corrections:
                logger.info("No folder corrections detected")
                return self._get_stats("completed", "No corrections found")

            logger.info(f"Found {len(corrections)} folder correction(s)")
            self.stats["corrections_found"] = len(corrections)

            # Process each correction
            for i, correction in enumerate(corrections):
                if i > 0:
                    time.sleep(1)  # Delay between LLM calls
                self._process_single_correction(correction)

            # Cleanup old learning data if configured
            self._cleanup_old_learning()

            return self._get_stats("completed", f"Processed {len(corrections)} correction(s)")

        except Exception as e:
            logger.error(f"Error during folder reconciliation: {e}")
            self.stats["errors"] += 1
            return self._get_stats("error", f"Reconciliation failed: {e!s}")

    def _build_folder_maps(self) -> tuple[Dict[str, str], Dict[str, str]]:
        """Build bidirectional folder ↔ classification maps from config."""
        folder_to_class: Dict[str, str] = {}
        class_to_folder: Dict[str, str] = {}

        for cat in config.CATEGORIES:
            if cat.is_default:
                folder_to_class[config.INBOX_FOLDER] = cat.name
                class_to_folder[cat.name] = config.INBOX_FOLDER
            elif cat.folder:
                folder_to_class[cat.folder] = cat.name
                class_to_folder[cat.name] = cat.folder

        return folder_to_class, class_to_folder

    def _scan_all_folders(
        self, folder_to_class: Dict[str, str], since_days: int
    ) -> Optional[Dict[str, str]]:
        """Scan all category folders and return {message_id → folder_name}.

        Uses a single IMAP connection for all folder scans.
        """
        all_folder_emails: Dict[str, str] = {}

        try:
            with EmailClient() as client:
                for folder in folder_to_class:
                    message_ids = client.get_folder_message_ids(folder, since_days)
                    for mid in message_ids:
                        all_folder_emails[mid] = folder

            logger.debug(
                f"Scanned {len(folder_to_class)} folders, found {len(all_folder_emails)} emails"
            )
            return all_folder_emails

        except Exception as e:
            logger.error(f"Error scanning folders: {e}")
            return None

    def _find_corrections(
        self,
        recent_emails: List[Dict[str, Any]],
        all_folder_emails: Dict[str, str],
        folder_to_class: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Compare DB records with actual folder locations to find corrections."""
        corrections = []

        for email_record in recent_emails:
            message_id = email_record["message_id"]
            if not message_id:
                continue

            # Where the system put it (or INBOX if not moved)
            expected_folder = email_record["folder_moved_to"] or config.INBOX_FOLDER

            # Where it actually is now
            actual_folder = all_folder_emails.get(message_id)

            if actual_folder is None:
                # Email not found in any known folder (deleted, archived, etc.) → skip
                continue

            if actual_folder != expected_folder:
                # User moved the email → correction detected
                new_classification = folder_to_class.get(actual_folder)
                if not new_classification:
                    continue

                corrections.append({
                    "message_id": message_id,
                    "email_id": email_record["email_id"],
                    "subject": email_record["subject"],
                    "sender": email_record["sender"],
                    "old_classification": email_record["classification"],
                    "new_classification": new_classification,
                    "old_folder": expected_folder,
                    "new_folder": actual_folder,
                })

        return corrections

    def _process_single_correction(self, correction: Dict[str, Any]) -> None:
        """Process a single folder correction: generate learning + update DB."""
        message_id = correction["message_id"]
        old_class = correction["old_classification"]
        new_class = correction["new_classification"]
        old_folder = correction["old_folder"]
        new_folder = correction["new_folder"]

        logger.info(
            f"Folder correction: '{correction['subject'][:50]}' "
            f"moved from {old_folder} to {new_folder} "
            f"({old_class} → {new_class})"
        )

        try:
            # Fetch full email for LLM summary generation
            email_data = self._fetch_full_email(message_id, new_folder)

            if not email_data:
                logger.warning(f"Cannot fetch email {message_id} for learning, saving template summary")
                # Use template-based summary as fallback
                learning_summary = (
                    f"Email from {correction['sender']} with subject '{correction['subject']}' "
                    f"was classified as {old_class} but user moved it to {new_folder}, "
                    f"indicating it should be {new_class}."
                )
            else:
                # Generate LLM-based learning summary
                learning_summary = self.learning_generator.generate_learning_summary(
                    email_data, old_folder, new_class
                )
                if not learning_summary:
                    logger.warning(f"LLM summary failed for {message_id}, using template")
                    learning_summary = (
                        f"Email from {correction['sender']} with subject '{correction['subject']}' "
                        f"was classified as {old_class} but user moved it to {new_folder}, "
                        f"indicating it should be {new_class}."
                    )

            # Determine learning type
            default_name = config.default_category.name
            if new_class == default_name:
                learning_type = f"false_positive_{old_class}"
            elif old_class == default_name:
                learning_type = f"false_negative_{new_class}"
            else:
                learning_type = f"{old_class}_to_{new_class}"

            # Extract domain
            sender = correction["sender"]
            email_domain = ""
            if "@" in sender:
                with contextlib.suppress(Exception):
                    email_domain = sender.split("@")[1].split(">")[0].strip()

            # Save learning record
            learning_data = LearningData(
                message_id=message_id,
                source_folder=old_folder,
                target_classification=new_class,
                learning_type=learning_type,
                email_subject=correction["subject"],
                email_sender=sender,
                email_domain=email_domain,
                learning_summary=learning_summary,
                confidence_score=1.0,
                created_at=datetime.now().isoformat(),
            )

            if self.db_manager.save_learning_data(learning_data):
                self.stats["learning_generated"] += 1
                logger.debug(f"Learning saved for {message_id}: {learning_type}")
            else:
                self.stats["errors"] += 1
                logger.error(f"Failed to save learning for {message_id}")
                return

            # Update DB so we don't re-detect this correction
            new_folder_value = new_folder if new_folder != config.INBOX_FOLDER else None
            self.db_manager.update_folder_moved_to(message_id, new_folder_value)

        except Exception as e:
            logger.error(f"Error processing correction for {message_id}: {e}")
            self.stats["errors"] += 1

    def _fetch_full_email(self, message_id: str, folder: str) -> Optional[Dict[str, Any]]:
        """Fetch full email content from the folder it's currently in."""
        try:
            with EmailClient() as client:
                if not client.select_folder(folder):
                    return None
                return client.fetch_email_by_message_id(message_id)
        except Exception as e:
            logger.error(f"Error fetching email {message_id} from {folder}: {e}")
            return None

    def _cleanup_old_learning(self):
        """Clean up old learning data if retention is configured."""
        try:
            if config.LEARNING_RETENTION_DAYS > 0:
                deleted_count = self.db_manager.cleanup_old_learning(config.LEARNING_RETENTION_DAYS)
                if deleted_count > 0:
                    logger.debug(f"Cleaned up {deleted_count} old learning records")
        except Exception as e:
            logger.error(f"Error cleaning up old learning data: {e}")

    def _reset_stats(self):
        """Reset processing statistics."""
        self.stats = {
            "corrections_found": 0,
            "learning_generated": 0,
            "errors": 0,
        }

    def _get_stats(self, status: str, message: str) -> Dict[str, Any]:
        """Get processing statistics."""
        return {"status": status, "message": message, **self.stats}
