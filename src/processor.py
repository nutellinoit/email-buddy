"""
Main email processing logic for configurable email classification and management.
"""

import logging
import os
import time as _time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .config import config
from .database import get_database_manager
from .email_classifier import EmailClassifier
from .email_client import EmailClient
from .learning import LearningProcessor
from .models import ProcessedEmail

logger = logging.getLogger(__name__)


class EmailProcessor:
    """Main email processor for configurable classification and management."""

    def __init__(self):
        self.email_client = EmailClient()
        self.email_classifier = EmailClassifier()
        self.db_manager = get_database_manager()
        self.learning_processor = LearningProcessor()
        self.stats = self._build_initial_stats()

    def _build_initial_stats(self) -> Dict[str, Any]:
        """Build initial stats dictionary from configured categories."""
        stats: Dict[str, Any] = {
            "processed": 0,
            "skipped": 0,
            "classification_failed": 0,
            "errors": 0,
            "learning_emails_processed": 0,
            "learning_generated": 0,
            "learning_errors": 0,
        }
        for cat_name in config.category_names:
            stats[f"{cat_name}_detected"] = 0
            if not config.category_map[cat_name].is_default:
                stats[f"{cat_name}_moved"] = 0
        return stats

    def process_emails(self) -> Dict[str, Any]:
        """
        Main processing function that handles the entire email processing workflow.

        Returns:
            Dictionary containing processing statistics and results
        """
        logger.debug("Starting email processing...")

        # Reset stats
        self.stats = self._build_initial_stats()
        self.stats["start_time"] = datetime.now().isoformat()

        try:
            # Clean up old processed emails if configured
            if config.EMAIL_RETENTION_DAYS > 0:
                deleted_count = self.db_manager.cleanup_old_records(config.EMAIL_RETENTION_DAYS)
                if deleted_count > 0:
                    self.stats["emails_cleaned_up"] = deleted_count
                    logger.info(f"Cleaned up {deleted_count} old processed email records")
            # Check LLM provider availability
            if not self.email_classifier.is_available():
                logger.warning("LLM provider not available, emails will be skipped until LLM is back")

            # Process emails using atomic one-at-a-time approach
            processed_count = 0
            max_emails = config.EMAIL_LIMIT

            while processed_count < max_emails:
                # Use fresh connection for each email
                with self.email_client as client:
                    # Select inbox folder
                    if not client.select_folder(config.INBOX_FOLDER):
                        raise Exception(f"Failed to select inbox folder: {config.INBOX_FOLDER}")

                    # Get next unprocessed email
                    email_data = client.get_next_unprocessed_email(self.db_manager)

                    if not email_data:
                        logger.debug(f"No more unprocessed emails found after processing {processed_count}")
                        break

                    # Process this email atomically: classify -> move -> save
                    success = self._process_single_email_atomic(email_data)
                    if success:
                        processed_count += 1
                        logger.debug(f"Successfully processed email {processed_count}/{max_emails}")
                    else:
                        logger.warning("Failed to process email, but continuing...")

                # Small delay between emails to prevent server overload
                if processed_count < max_emails:
                    import time

                    time.sleep(0.5)

            # Process learning workflow if enabled and due
            self._process_learning_workflow()

            result_msg = f"Email processing completed - processed {processed_count} emails"
            logger.debug(result_msg)
            return self._get_results("completed", result_msg)

        except Exception as e:
            logger.error(f"Error during email processing: {e}")
            self.stats["errors"] += 1
            return self._get_results("error", f"Processing failed: {e!s}")

    def _process_single_email_atomic(self, email_data: Dict[str, Any]) -> bool:
        """Process a single email atomically: classify -> move -> save in one operation."""
        try:
            email_id = email_data.get("id", "unknown")
            subject = email_data.get("subject", "No Subject")
            sender = email_data.get("sender", "Unknown Sender")
            is_unread = email_data.get("is_unread", False)

            logger.debug(f"Processing email {email_id}: '{subject}' from {sender} (unread: {is_unread})")

            # Classify email immediately after fetch (measure LLM time)
            classify_start = _time.time()
            classification_result = self.email_classifier.classify_with_fallback(email_data)
            classify_elapsed = _time.time() - classify_start

            # Handle classification failure (None return)
            if classification_result is None:
                self.stats["classification_failed"] += 1
                logger.error(f"Classification failed for email {email_id}")
                return False

            category, confidence, reason = classification_result
            self.stats["processed"] += 1

            # Look up category config
            cat_config = config.category_map.get(category)
            if not cat_config:
                cat_config = config.default_category
                category = cat_config.name

            # Update detection stats
            detected_key = f"{category}_detected"
            self.stats[detected_key] = self.stats.get(detected_key, 0) + 1

            # Handle email based on classification
            folder_moved_to = None
            backup_path = None
            move_success = False

            if cat_config.is_default or not cat_config.folder:
                # Default category: leave in inbox
                logger.debug(f"Email {email_id} classified as {category} - left in inbox")
                move_success = True
                folder_moved_to = None
                action = "left in INBOX"
            elif confidence >= cat_config.threshold:
                # Non-default category with sufficient confidence: move to target folder
                move_success, folder_moved_to, backup_path = self._handle_email_move_atomic(
                    email_data, cat_config.folder, category, confidence, reason
                )
                action = f"moved to {cat_config.folder}" if move_success else "MOVE FAILED"
            else:
                # Below threshold: treat as default
                default_name = config.default_category.name
                logger.debug(
                    f"Email {email_id} classified as {category} but below threshold "
                    f"({confidence:.2f} < {cat_config.threshold}) - treating as {default_name}"
                )
                move_success = True
                folder_moved_to = None
                category = default_name
                action = "below threshold, left in INBOX"

            # Consolidated per-email log (2 lines)
            sender_short = sender.split("<")[0].strip() if "<" in sender else sender
            logger.info(f"  {email_id[:8]} \"{subject[:60]}\" from {sender_short}")
            logger.info(
                f"    \u2192 {category.upper()} ({confidence:.2f}, {classify_elapsed:.1f}s) \u2192 {action}"
            )

            # Only save as processed if the entire operation succeeded
            if move_success:
                processed_email = ProcessedEmail.from_email_data(
                    email_data, category, confidence, reason, folder_moved_to, backup_path
                )
                if self.db_manager.save_processed_email(processed_email):
                    logger.debug(f"Email {email_id} successfully processed and saved to database")
                    return True
                else:
                    logger.error(f"Failed to save processed email {email_id} to database")
                    self.stats["errors"] += 1
                    return False
            else:
                logger.error(f"Email {email_id} move operation failed")
                self.stats["processed"] -= 1
                return False

        except Exception as e:
            logger.error(f"Error in atomic processing of email {email_data.get('id', 'unknown')}: {e}")
            self.stats["errors"] += 1
            return False

    def _handle_email_move_atomic(
        self, email_data: Dict[str, Any], destination_folder: str, category: str, confidence: float, reason: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Handle email move operation atomically with proper error handling.

        Returns:
            Tuple of (success, folder_moved_to, backup_path)
        """
        email_id = email_data.get("id", "unknown")
        subject = email_data.get("subject", "No Subject")

        if config.DRY_RUN:
            logger.info(f"DRY RUN: Would move {category} email {email_id} to {destination_folder}")
            logger.info(f"DRY RUN: Subject: '{subject}', Confidence: {confidence:.2f}, Reason: {reason}")
            return True, destination_folder, None

        try:
            # Save backup BEFORE moving (safety net against data loss)
            backup_path = self._save_email_backup(email_data, category)

            # Mark as read in INBOX before moving if configured
            if config.MARK_AS_READ_WHEN_MOVE and email_data.get("is_unread", False):
                if self.email_client.mark_as_read(email_data, config.INBOX_FOLDER):
                    logger.debug(f"Marked {category} email {email_id} as read before moving")
                else:
                    logger.warning(f"Failed to mark {category} email {email_id} as read before moving")

            # Attempt atomic move with flag preservation
            if self.email_client.move_email(email_data, destination_folder):
                logger.debug(f"Moved {category} email {email_id} to {destination_folder}")
                moved_key = f"{category}_moved"
                if moved_key in self.stats:
                    self.stats[moved_key] += 1
                return True, destination_folder, backup_path
            else:
                logger.error(f"Failed to move {category} email {email_id}")
                self.stats["errors"] += 1
                return False, None, backup_path

        except Exception as e:
            logger.error(f"Error moving {category} email {email_id}: {e}")
            self.stats["errors"] += 1
            return False, None, None

    def _save_email_backup(self, email_data: Dict[str, Any], category: str) -> Optional[str]:
        """Save raw email to disk as .eml backup before IMAP move.

        Returns:
            The file path if saved successfully, None otherwise.
        """
        if not config.EMAIL_BACKUP_ENABLED:
            return None

        email_id = email_data.get("id", "unknown")
        raw_message = email_data.get("raw_message")
        if not raw_message:
            logger.warning(f"No raw_message available for email {email_id}, skipping backup")
            return None

        try:
            # Build path: {EMAIL_BACKUP_PATH}/{category}/{content_id}.eml
            category_dir = os.path.join(config.EMAIL_BACKUP_PATH, category)
            os.makedirs(category_dir, exist_ok=True)

            content_id = email_data.get("content_id") or email_data.get("id", "unknown")
            file_path = os.path.join(category_dir, f"{content_id}.eml")

            # Write raw RFC822 message
            raw_bytes = raw_message.as_bytes()
            with open(file_path, "wb") as f:
                f.write(raw_bytes)

            logger.debug(f"Backup saved: {file_path} ({len(raw_bytes)} bytes)")
            return file_path

        except Exception as e:
            logger.warning(f"Failed to save email backup for {email_id}: {e}")
            return None

    def _process_learning_workflow(self):
        """Process the learning workflow via folder reconciliation."""
        try:
            if not config.LEARNING_ENABLED:
                return

            logger.debug("Running folder reconciliation...")

            learning_results = self.learning_processor.reconcile_folders()

            if learning_results.get("status") == "completed":
                self.stats["learning_emails_processed"] = learning_results.get("corrections_found", 0)
                self.stats["learning_generated"] = learning_results.get("learning_generated", 0)
                self.stats["learning_errors"] = learning_results.get("errors", 0)

                generated = learning_results.get("learning_generated", 0)
                corrections = learning_results.get("corrections_found", 0)
                if generated > 0:
                    logger.info(f"Reconciliation: {corrections} corrections, {generated} learning rules generated")
                else:
                    logger.info("Reconciliation: no corrections")
            else:
                if learning_results.get("status") != "skipped":
                    self.stats["learning_errors"] += 1
                    logger.error(f"Folder reconciliation failed: {learning_results.get('message', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error in learning workflow: {e}")
            self.stats["learning_errors"] += 1

    def _get_results(self, status: str, message: str) -> Dict[str, Any]:
        """Get processing results with statistics."""
        db_stats = self.db_manager.get_statistics()

        learning_stats = {}
        if config.LEARNING_ENABLED:
            try:
                learning_stats = self.db_manager.get_learning_statistics()
            except Exception as e:
                logger.error(f"Error getting learning statistics: {e}")

        self.stats.update(
            {
                "status": status,
                "message": message,
                "end_time": datetime.now().isoformat(),
                "database_stats": db_stats,
                "learning_stats": learning_stats,
                "config": {
                    "email_limit": config.EMAIL_LIMIT,
                    "dry_run": config.DRY_RUN,
                    "categories": [
                        {"name": c.name, "folder": c.folder, "threshold": c.threshold, "is_default": c.is_default}
                        for c in config.CATEGORIES
                    ],
                    "inbox_folder": config.INBOX_FOLDER,
                    "database_path": config.DATABASE_PATH,
                },
            }
        )

        return self.stats

    def validate_configuration(self) -> List[str]:
        """Validate configuration before processing."""
        errors = config.validate()

        try:
            with EmailClient() as client:
                if not client.select_folder(config.INBOX_FOLDER):
                    errors.append(f"Cannot access inbox folder: {config.INBOX_FOLDER}")
        except Exception as e:
            errors.append(f"Cannot connect to email server: {e!s}")

        if not self.email_classifier.is_available():
            logger.warning("LLM not available - emails will be skipped until LLM is back")

        try:
            self.db_manager.get_statistics()
        except Exception as e:
            errors.append(f"Cannot access database: {e!s}")

        return errors

    def get_stats(self) -> Dict[str, Any]:
        """Get current processing statistics."""
        return self.stats.copy()


def run_email_processor() -> Dict[str, Any]:
    """
    Convenience function to run the email processor.

    Returns:
        Processing results dictionary
    """
    processor = EmailProcessor()

    errors = processor.validate_configuration()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return {"status": "error", "message": "Configuration validation failed", "errors": errors}

    return processor.process_emails()
