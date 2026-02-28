"""
Main entry point for Email-Buddy spam processor.
"""

import logging
import os
import sys
import time
from typing import Any, Dict

from .config import config
from .processor import run_email_processor


# Configure logging
def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper()),
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from some libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def print_configuration():
    """Print current configuration (without sensitive data)."""
    logger = logging.getLogger(__name__)

    logger.info("=== Email-Buddy Configuration ===")
    logger.info(f"IMAP Host: {config.IMAP_HOST}:{config.IMAP_PORT}")
    logger.info(f"IMAP Username: {config.IMAP_USERNAME}")
    logger.info(f"IMAP SSL: {config.IMAP_USE_SSL}")
    logger.info(f"Inbox Folder: {config.INBOX_FOLDER}")
    logger.info(f"Email Limit: {config.EMAIL_LIMIT}")
    logger.info(f"Email Fetch Days: {config.EMAIL_FETCH_DAYS}")
    logger.info(f"LLM Model: {config.LITELLM_MODEL}")
    logger.info(f"LLM API Base: {config.LITELLM_API_BASE}")
    logger.info(f"LLM Timeout: {config.LITELLM_TIMEOUT}s")
    logger.info(f"Database Path: {config.DATABASE_PATH}")
    logger.info(f"Dry Run: {config.DRY_RUN}")
    logger.info(f"Process Interval: {config.PROCESS_INTERVAL}s")
    logger.info(f"IDLE Enabled: {config.IDLE_ENABLED}")
    logger.info(f"Daily Summary: {'enabled' if config.DAILY_SUMMARY_ENABLED else 'disabled'}")
    if config.DAILY_SUMMARY_ENABLED:
        logger.info(f"Daily Summary Hour: {config.DAILY_SUMMARY_HOUR}:00")
        logger.info(f"Daily Summary Language: {config.DAILY_SUMMARY_LANGUAGE}")
    logger.info("Categories:")
    for cat in config.CATEGORIES:
        default_marker = " [DEFAULT]" if cat.is_default else ""
        folder = cat.folder or "INBOX (no move)"
        logger.info(f"  - {cat.name} | {folder}{default_marker} | {cat.description}")
    logger.info("==================================")


def print_results(results: Dict[str, Any]):
    """Print compact processing results."""
    logger = logging.getLogger(__name__)

    processed = results.get("processed", 0)
    errors = results.get("errors", 0)
    failed = results.get("classification_failed", 0)

    if processed == 0 and errors == 0 and failed == 0:
        logger.info("Cycle: no emails processed")
        return

    # Compact summary line
    parts = [f"{processed} processed"]
    if errors:
        parts.append(f"{errors} errors")
    if failed:
        parts.append(f"{failed} classification failures")

    db_stats = results.get("database_stats", {})
    db_total = db_stats.get("total_processed", 0)
    db_24h = db_stats.get("recent_processed_24h", 0)
    if db_total:
        parts.append(f"DB: {db_total} total, {db_24h} last 24h")

    logger.info(f"Cycle completed: {' | '.join(parts)}")

    # Per-category breakdown (only non-zero)
    cat_parts = []
    for cat_name in config.category_names:
        detected = results.get(f"{cat_name}_detected", 0)
        moved = results.get(f"{cat_name}_moved", 0)
        if detected > 0:
            if moved > 0:
                cat_parts.append(f"{cat_name}: {detected} detected, {moved} moved")
            else:
                cat_parts.append(f"{cat_name}: {detected}")
    if cat_parts:
        logger.info(f"  {' | '.join(cat_parts)}")


def run_once() -> bool:
    """Run email processing once."""
    logger = logging.getLogger(__name__)

    try:
        logger.debug("Starting Email-Buddy spam processor...")

        # Run processing
        results = run_email_processor()

        # Print results
        print_results(results)

        # Return success status
        return results.get("status") == "completed"

    except KeyboardInterrupt:
        logger.info("Processing interrupted by user")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return False


def run_daemon():
    """Run email processing in daemon mode with intervals."""
    logger = logging.getLogger(__name__)

    logger.info(f"Starting Email-Buddy daemon mode (interval: {config.PROCESS_INTERVAL}s)")

    # Set up IDLE watcher if enabled
    idle_watcher = None
    if config.IDLE_ENABLED:
        from .idle_watcher import IMAPIdleWatcher

        idle_watcher = IMAPIdleWatcher()
        logger.info("IMAP IDLE enabled -- will watch INBOX for real-time notifications")
    else:
        logger.info("IMAP IDLE disabled -- using periodic polling only")

    # Set up daily summary generator if enabled
    summary_generator = None
    if config.DAILY_SUMMARY_ENABLED:
        from .daily_summary import DailySummaryGenerator

        summary_generator = DailySummaryGenerator()
        logger.info(f"Daily summary enabled -- will generate at {config.DAILY_SUMMARY_HOUR}:00")

    try:
        while True:
            logger.debug("Starting processing cycle...")

            success = run_once()

            if success:
                logger.debug("Processing cycle completed successfully")
            else:
                logger.error("Processing cycle failed")

            # Check if daily summary is due
            if summary_generator and summary_generator.is_summary_due():
                try:
                    summary_generator.generate_and_send()
                except Exception as e:
                    logger.error(f"Daily summary generation failed: {e}")

            # Wait for next cycle: IDLE (real-time) or sleep (polling)
            if idle_watcher and config.PROCESS_INTERVAL > 0:
                logger.info(f"Waiting for new mail (IDLE, timeout {config.PROCESS_INTERVAL}s)...")
                new_mail = idle_watcher.wait_for_changes(timeout=config.PROCESS_INTERVAL)
                if new_mail:
                    logger.info("New mail detected via IDLE")
                    time.sleep(2)  # Allow IMAP server to index the new message
                else:
                    logger.debug("Periodic check (no IDLE notification)")
            elif config.PROCESS_INTERVAL > 0:
                logger.debug(f"Waiting {config.PROCESS_INTERVAL} seconds until next cycle...")
                time.sleep(config.PROCESS_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Daemon mode interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error in daemon mode: {e}", exc_info=True)


def main():
    """Main function."""
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)

    version = os.environ.get("APP_VERSION", "dev")
    logger.info(f"Email-Buddy {version}")

    # Print configuration
    print_configuration()

    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    # Verify LLM structured output capability (fail fast if model is incompatible)
    from .llm import verify_llm_structured_output

    try:
        logger.info("Verifying LLM structured output capability...")
        verify_llm_structured_output()
        logger.info("LLM probe successful")
    except RuntimeError as e:
        logger.error(f"LLM capability check failed: {e}")
        sys.exit(1)

    # Start read-only API server in background thread
    from .api.app import start_api_server

    start_api_server()

    # Special handling for dry run mode
    if config.DRY_RUN:
        logger.warning("DRY RUN MODE: No emails will be moved, only logged")

    # Determine run mode
    if config.PROCESS_INTERVAL > 0:
        # Daemon mode
        run_daemon()
    else:
        # One-shot mode
        success = run_once()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
