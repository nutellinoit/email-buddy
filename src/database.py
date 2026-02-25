"""
Database manager for Email-Buddy email tracking system.
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .config import config
from .models import DailySummary, EmailDatabase, LearningData, ProcessedEmail

logger = logging.getLogger(__name__)


class EmailDatabaseManager:
    """Manager for email processing database operations."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.init_database()

    def init_database(self):
        """Initialize the database with required tables and indexes."""
        try:
            # Ensure the directory exists
            import os

            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"Created database directory: {db_dir}")

            EmailDatabase.init_database(self.db_path)
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            logger.error(f"Database path: {self.db_path}")
            logger.error(
                f"Database directory exists: {os.path.exists(os.path.dirname(self.db_path)) if os.path.dirname(self.db_path) else 'N/A'}"
            )
            raise

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = None
        try:
            conn = EmailDatabase.get_connection(self.db_path)
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def is_email_processed(self, email_data: Dict[str, Any]) -> bool:
        """Check if an email has already been processed using content-based identification."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Check by content_id first (primary method)
                content_id = email_data.get("content_id") or email_data.get("id", "")
                if content_id:
                    cursor.execute("SELECT COUNT(*) FROM processed_emails WHERE email_id = ?", (content_id,))
                    if cursor.fetchone()[0] > 0:
                        return True

                # Check by message_id (email header fallback)
                message_id = email_data.get("message_id", "")
                if message_id:
                    cursor.execute("SELECT COUNT(*) FROM processed_emails WHERE message_id = ?", (message_id,))
                    if cursor.fetchone()[0] > 0:
                        return True

                # Check by content hash as final fallback (backward compatibility)
                if "content_hash" in email_data:
                    content_hash = email_data["content_hash"]
                else:
                    content_for_hash = (
                        f"{email_data.get('subject', '')}{email_data.get('sender', '')}{email_data.get('body', '')}"
                    )
                    import hashlib

                    content_hash = hashlib.md5(content_for_hash.encode("utf-8"), usedforsecurity=False).hexdigest()

                cursor.execute("SELECT COUNT(*) FROM processed_emails WHERE content_hash = ?", (content_hash,))
                return cursor.fetchone()[0] > 0

        except Exception as e:
            logger.error(f"Error checking if email is processed: {e}")
            return False

    def save_processed_email(self, processed_email: ProcessedEmail) -> bool:
        """Save a processed email to the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Insert the processed email
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO processed_emails (
                        email_id, message_id, subject, sender, date_received,
                        classification, confidence, reason, folder_moved_to,
                        processed_at, content_hash, backup_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        processed_email.email_id,
                        processed_email.message_id,
                        processed_email.subject,
                        processed_email.sender,
                        processed_email.date_received,
                        processed_email.classification,
                        processed_email.confidence,
                        processed_email.reason,
                        processed_email.folder_moved_to,
                        processed_email.processed_at,
                        processed_email.content_hash,
                        processed_email.backup_path,
                    ),
                )

                conn.commit()
                logger.debug(f"Saved processed email: {processed_email.email_id}")
                return True

        except Exception as e:
            logger.error(f"Error saving processed email: {e}")
            return False

    def get_processed_emails(
        self, limit: Optional[int] = None, classification: Optional[str] = None
    ) -> List[ProcessedEmail]:
        """Get processed emails from the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                query = "SELECT * FROM processed_emails"
                params = []

                if classification:
                    query += " WHERE classification = ?"
                    params.append(classification)

                query += " ORDER BY processed_at DESC"

                if limit:
                    query += " LIMIT ?"
                    params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [ProcessedEmail.from_row(row) for row in rows]

        except Exception as e:
            logger.error(f"Error getting processed emails: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics from the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Total processed emails
                cursor.execute("SELECT COUNT(*) FROM processed_emails")
                total_processed = cursor.fetchone()[0]

                # Count by classification
                cursor.execute("""
                    SELECT classification, COUNT(*)
                    FROM processed_emails
                    GROUP BY classification
                """)
                by_classification = dict(cursor.fetchall())

                # Recent processing (last 24 hours)
                yesterday = (datetime.now() - timedelta(days=1)).isoformat()
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM processed_emails
                    WHERE processed_at >= ?
                """,
                    (yesterday,),
                )
                recent_processed = cursor.fetchone()[0]

                # Average confidence by classification
                cursor.execute("""
                    SELECT classification, AVG(confidence)
                    FROM processed_emails
                    GROUP BY classification
                """)
                avg_confidence = dict(cursor.fetchall())

                return {
                    "total_processed": total_processed,
                    "by_classification": by_classification,
                    "recent_processed_24h": recent_processed,
                    "average_confidence": avg_confidence,
                    "database_path": self.db_path,
                }

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                "total_processed": 0,
                "by_classification": {},
                "recent_processed_24h": 0,
                "average_confidence": {},
                "database_path": self.db_path,
            }

    def get_summary_statistics_since(self, since_datetime: datetime) -> Dict[str, Any]:
        """Get aggregated statistics for emails processed since a given datetime."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                since_iso = since_datetime.isoformat()

                # Total processed in period
                cursor.execute(
                    "SELECT COUNT(*) FROM processed_emails WHERE processed_at >= ?",
                    (since_iso,),
                )
                total = cursor.fetchone()[0]

                # By classification with average confidence
                cursor.execute(
                    """
                    SELECT classification, COUNT(*), AVG(confidence)
                    FROM processed_emails
                    WHERE processed_at >= ?
                    GROUP BY classification
                    """,
                    (since_iso,),
                )
                by_classification = {}
                avg_confidence = {}
                for row in cursor.fetchall():
                    by_classification[row[0]] = row[1]
                    avg_confidence[row[0]] = round(row[2], 3)

                # Top senders
                cursor.execute(
                    """
                    SELECT sender, COUNT(*) as cnt
                    FROM processed_emails
                    WHERE processed_at >= ?
                    GROUP BY sender
                    ORDER BY cnt DESC
                    LIMIT 5
                    """,
                    (since_iso,),
                )
                top_senders = dict(cursor.fetchall())

                # Learning entries in period
                cursor.execute(
                    "SELECT COUNT(*) FROM learning_data WHERE created_at >= ?",
                    (since_iso,),
                )
                learning_count = cursor.fetchone()[0]

                return {
                    "total_processed": total,
                    "by_classification": by_classification,
                    "average_confidence": avg_confidence,
                    "top_senders": top_senders,
                    "learning_entries": learning_count,
                }

        except Exception as e:
            logger.error(f"Error getting summary statistics: {e}")
            return {
                "total_processed": 0,
                "by_classification": {},
                "average_confidence": {},
                "top_senders": {},
                "learning_entries": 0,
            }

    def get_classification_timeline(
        self, since_datetime: datetime, bucket_size_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get classification counts grouped by time bucket for timeline charts."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                since_iso = since_datetime.isoformat()

                if bucket_size_hours >= 24:
                    time_expr = "date(processed_at)"
                else:
                    time_expr = "strftime('%Y-%m-%dT%H:00', processed_at)"

                query = (
                    f"SELECT {time_expr} as period, classification, COUNT(*) as count "  # nosec B608
                    "FROM processed_emails "
                    "WHERE processed_at >= ? "
                    "  AND classification != 'summary' "
                    "GROUP BY period, classification "
                    "ORDER BY period"
                )
                cursor.execute(query, (since_iso,))

                from collections import OrderedDict

                buckets: OrderedDict[str, Dict[str, Any]] = OrderedDict()
                for row in cursor.fetchall():
                    period = row[0]
                    classification = row[1]
                    count = row[2]
                    if period not in buckets:
                        buckets[period] = {"period": period}
                    buckets[period][classification] = count

                return list(buckets.values())

        except Exception as e:
            logger.error(f"Error getting classification timeline: {e}")
            return []

    def get_recent_email_details_since(
        self, since_datetime: datetime, limit: int = 20
    ) -> List[ProcessedEmail]:
        """Get individual recent email records for LLM context."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM processed_emails
                    WHERE processed_at >= ?
                      AND classification != 'summary'
                    ORDER BY processed_at DESC
                    LIMIT ?
                    """,
                    (since_datetime.isoformat(), limit),
                )
                return [ProcessedEmail.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting recent email details: {e}")
            return []

    def save_daily_summary(self, summary: DailySummary) -> bool:
        """Save a daily summary record to the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO daily_summaries (
                        generated_at, period_start, period_end,
                        total_processed, stats_json, narrative, delivered
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary.generated_at,
                        summary.period_start,
                        summary.period_end,
                        summary.total_processed,
                        summary.stats_json,
                        summary.narrative,
                        int(summary.delivered),
                    ),
                )
                conn.commit()
                logger.debug(f"Saved daily summary for {summary.generated_at}")
                return True

        except Exception as e:
            logger.error(f"Error saving daily summary: {e}")
            return False

    def get_recent_summaries(self, limit: int = 7) -> List[DailySummary]:
        """Get recent daily summaries for LLM cross-referencing."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM daily_summaries ORDER BY generated_at DESC LIMIT ?",
                    (limit,),
                )
                rows = cursor.fetchall()
                return [DailySummary.from_row(row) for row in rows]

        except Exception as e:
            logger.error(f"Error getting recent summaries: {e}")
            return []

    def is_summary_sent_today(self) -> bool:
        """Check if a daily summary has already been generated today."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                cursor.execute(
                    "SELECT COUNT(*) FROM daily_summaries WHERE DATE(generated_at) = ?",
                    (today,),
                )
                return cursor.fetchone()[0] > 0

        except Exception as e:
            logger.error(f"Error checking if summary sent today: {e}")
            return False

    def save_learning_data(self, learning_data: LearningData) -> bool:
        """Save learning data to the database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Insert the learning data
                cursor.execute(
                    """
                    INSERT INTO learning_data (
                        message_id, source_folder, target_classification, learning_type,
                        email_subject, email_sender, email_domain, sender_type,
                        content_type, learning_summary, confidence_score, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        learning_data.message_id,
                        learning_data.source_folder,
                        learning_data.target_classification,
                        learning_data.learning_type,
                        learning_data.email_subject,
                        learning_data.email_sender,
                        learning_data.email_domain,
                        learning_data.sender_type,
                        learning_data.content_type,
                        learning_data.learning_summary,
                        learning_data.confidence_score,
                        learning_data.created_at,
                    ),
                )

                conn.commit()
                logger.debug(f"Saved learning data for message: {learning_data.message_id}")
                return True

        except Exception as e:
            logger.error(f"Error saving learning data: {e}")
            return False

    def get_recent_learning(self, limit: int = 10, days: int = 30, learning_type: Optional[str] = None) -> List[str]:
        """Get recent learning summaries for prompt injection."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Calculate cutoff date
                cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

                query = """
                    SELECT learning_summary, learning_type, email_domain, sender_type, content_type
                    FROM learning_data
                    WHERE created_at >= ?
                """
                params = [cutoff_date]

                if learning_type:
                    query += " AND learning_type = ?"
                    params.append(learning_type)

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                # Format learning summaries for prompt injection
                summaries = []
                for row in rows:
                    summary = row[0]
                    row_learning_type = row[1]
                    domain = row[2] or "unknown"
                    summaries.append(f"[{row_learning_type.upper()}] {summary} (Domain: {domain})")

                return summaries

        except Exception as e:
            logger.error(f"Error getting recent learning: {e}")
            return []

    def get_learning_by_type(self, learning_type: str, limit: int = 5) -> List[LearningData]:
        """Get learning data by specific type."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT * FROM learning_data
                    WHERE learning_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (learning_type, limit),
                )

                rows = cursor.fetchall()
                return [LearningData.from_row(row) for row in rows]

        except Exception as e:
            logger.error(f"Error getting learning by type: {e}")
            return []

    def get_learning_statistics(self) -> Dict[str, Any]:
        """Get learning statistics."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Total learning entries
                cursor.execute("SELECT COUNT(*) FROM learning_data")
                total_learning = cursor.fetchone()[0]

                # Count by learning type
                cursor.execute("""
                    SELECT learning_type, COUNT(*)
                    FROM learning_data
                    GROUP BY learning_type
                """)
                by_learning_type = dict(cursor.fetchall())

                # Recent learning (last 7 days)
                week_ago = (datetime.now() - timedelta(days=7)).isoformat()
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM learning_data
                    WHERE created_at >= ?
                """,
                    (week_ago,),
                )
                recent_learning = cursor.fetchone()[0]

                # Top domains being learned
                cursor.execute("""
                    SELECT email_domain, COUNT(*)
                    FROM learning_data
                    WHERE email_domain IS NOT NULL AND email_domain != ''
                    GROUP BY email_domain
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """)
                top_domains = dict(cursor.fetchall())

                return {
                    "total_learning_entries": total_learning,
                    "by_learning_type": by_learning_type,
                    "recent_learning_7d": recent_learning,
                    "top_learning_domains": top_domains,
                }

        except Exception as e:
            logger.error(f"Error getting learning statistics: {e}")
            return {
                "total_learning_entries": 0,
                "by_learning_type": {},
                "recent_learning_7d": 0,
                "top_learning_domains": {},
            }

    def get_sender_statistics(self, sender_email: str, sender_domain: str) -> Dict[str, int]:
        """Get historical classification statistics for a sender and domain."""
        try:
            from .config import config

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Initialize counters dynamically from configured categories
                stats: Dict[str, int] = {"sender_total": 0, "domain_total": 0}
                for cat_name in config.category_names:
                    stats[f"sender_{cat_name}"] = 0
                    stats[f"domain_{cat_name}"] = 0

                # Get sender-specific statistics
                if sender_email:
                    cursor.execute(
                        """
                        SELECT classification, COUNT(*)
                        FROM processed_emails
                        WHERE LOWER(sender) LIKE LOWER(?)
                        GROUP BY classification
                    """,
                        (f"%{sender_email}%",),
                    )

                    for classification, count in cursor.fetchall():
                        key = f"sender_{classification}"
                        if key in stats:
                            stats[key] = count
                        stats["sender_total"] += count

                # Get domain-specific statistics
                if sender_domain:
                    cursor.execute(
                        """
                        SELECT classification, COUNT(*)
                        FROM processed_emails
                        WHERE LOWER(sender) LIKE LOWER(?)
                        GROUP BY classification
                    """,
                        (f"%{sender_domain}%",),
                    )

                    for classification, count in cursor.fetchall():
                        key = f"domain_{classification}"
                        if key in stats:
                            stats[key] = count
                        stats["domain_total"] += count

                return stats

        except Exception as e:
            logger.error(f"Error getting sender statistics: {e}")
            stats: Dict[str, int] = {"sender_total": 0, "domain_total": 0}
            for cat_name in config.category_names:
                stats[f"sender_{cat_name}"] = 0
                stats[f"domain_{cat_name}"] = 0
            return stats

    def cleanup_old_learning(self, days_to_keep: int = 30) -> int:
        """Clean up old learning data."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Calculate cutoff date
                cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()

                # Delete old learning records
                cursor.execute(
                    """
                    DELETE FROM learning_data
                    WHERE created_at < ?
                """,
                    (cutoff_date,),
                )

                deleted_count = cursor.rowcount
                conn.commit()

                logger.info(f"Cleaned up {deleted_count} old learning records older than {days_to_keep} days")
                return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up old learning data: {e}")
            return 0

    def cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """Clean up old processed email records and their backup files."""
        try:
            import os

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Calculate cutoff date
                cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()

                # Collect backup file paths before deleting records
                cursor.execute(
                    "SELECT backup_path FROM processed_emails WHERE processed_at < ? AND backup_path IS NOT NULL",
                    (cutoff_date,),
                )
                backup_paths = [row[0] for row in cursor.fetchall()]

                # Delete old records
                cursor.execute(
                    """
                    DELETE FROM processed_emails
                    WHERE processed_at < ?
                """,
                    (cutoff_date,),
                )

                deleted_count = cursor.rowcount
                conn.commit()

                # Delete backup files
                files_deleted = 0
                for path in backup_paths:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            files_deleted += 1
                    except OSError as e:
                        logger.warning(f"Failed to delete backup file {path}: {e}")

                if files_deleted > 0:
                    logger.info(f"Deleted {files_deleted} backup .eml files")

                logger.info(f"Cleaned up {deleted_count} old records older than {days_to_keep} days")
                return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up old records: {e}")
            return 0

    def get_duplicate_emails(self) -> List[Tuple[str, int]]:
        """Get emails that might be duplicates based on content hash."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT content_hash, COUNT(*) as count
                    FROM processed_emails
                    GROUP BY content_hash
                    HAVING COUNT(*) > 1
                """)

                return cursor.fetchall()

        except Exception as e:
            logger.error(f"Error finding duplicate emails: {e}")
            return []

    def export_to_csv(self, output_path: str) -> bool:
        """Export processed emails to CSV file."""
        try:
            import csv

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM processed_emails ORDER BY processed_at DESC")
                rows = cursor.fetchall()

                with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                    if rows:
                        fieldnames = rows[0].keys()
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()

                        for row in rows:
                            writer.writerow(dict(row))

                logger.info(f"Exported {len(rows)} records to {output_path}")
                return True

        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            return False

    def get_recent_classified_with_folders(self, days: int) -> List[Dict[str, Any]]:
        """Get recent processed emails with their expected folder location."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                cursor.execute(
                    """
                    SELECT message_id, email_id, classification, folder_moved_to, subject, sender
                    FROM processed_emails
                    WHERE processed_at >= ?
                      AND message_id != ''
                      AND classification != 'summary'
                    ORDER BY processed_at DESC
                    """,
                    (cutoff,),
                )
                return [
                    {
                        "message_id": row[0],
                        "email_id": row[1],
                        "classification": row[2],
                        "folder_moved_to": row[3],
                        "subject": row[4],
                        "sender": row[5],
                    }
                    for row in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error getting recent classified emails with folders: {e}")
            return []

    def update_folder_moved_to(self, message_id: str, new_folder: Optional[str]) -> bool:
        """Update folder_moved_to after a user correction is detected."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE processed_emails SET folder_moved_to = ? WHERE message_id = ?",
                    (new_folder, message_id),
                )
                conn.commit()
                logger.debug(f"Updated folder_moved_to for {message_id} → {new_folder}")
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating folder_moved_to for {message_id}: {e}")
            return False

    def find_original_classification_by_content_id(self, content_id: str) -> Optional[Dict[str, Any]]:
        """Find original classification for an email by content_id (primary method)."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT email_id, classification, confidence, reason, folder_moved_to, processed_at
                    FROM processed_emails
                    WHERE email_id = ?
                    ORDER BY processed_at DESC
                    LIMIT 1
                """,
                    (content_id,),
                )

                row = cursor.fetchone()
                if row:
                    return {
                        "email_id": row[0],
                        "classification": row[1],
                        "confidence": row[2],
                        "reason": row[3],
                        "folder_moved_to": row[4],
                        "processed_at": row[5],
                    }
                return None

        except Exception as e:
            logger.error(f"Error finding original classification for content_id {content_id}: {e}")
            return None

    def find_original_classification_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Find original classification for an email by message_id."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT email_id, classification, confidence, reason, folder_moved_to, processed_at
                    FROM processed_emails
                    WHERE message_id = ?
                    ORDER BY processed_at DESC
                    LIMIT 1
                """,
                    (message_id,),
                )

                row = cursor.fetchone()
                if row:
                    return {
                        "email_id": row[0],
                        "classification": row[1],
                        "confidence": row[2],
                        "reason": row[3],
                        "folder_moved_to": row[4],
                        "processed_at": row[5],
                    }
                return None

        except Exception as e:
            logger.error(f"Error finding original classification for message_id {message_id}: {e}")
            return None

    def find_original_classification(self, email_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find original classification using best available identifier."""
        # Try content_id first (most reliable)
        content_id = email_data.get("content_id") or email_data.get("id", "")
        if content_id:
            result = self.find_original_classification_by_content_id(content_id)
            if result:
                return result

        # Try message_id as fallback
        message_id = email_data.get("message_id", "")
        if message_id:
            result = self.find_original_classification_by_message_id(message_id)
            if result:
                return result

        # Try content_hash as final fallback
        if "content_hash" in email_data:
            content_hash = email_data["content_hash"]
        else:
            content_for_hash = (
                f"{email_data.get('subject', '')}{email_data.get('sender', '')}{email_data.get('body', '')}"
            )
            import hashlib

            content_hash = hashlib.md5(content_for_hash.encode("utf-8"), usedforsecurity=False).hexdigest()

        return self.find_original_classification_by_content_hash(content_hash)

    def find_original_classification_by_content_hash(self, content_hash: str) -> Optional[Dict[str, Any]]:
        """Find original classification for an email by content_hash (fallback method)."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT email_id, classification, confidence, reason, folder_moved_to, processed_at
                    FROM processed_emails
                    WHERE content_hash = ?
                    ORDER BY processed_at DESC
                    LIMIT 1
                """,
                    (content_hash,),
                )

                row = cursor.fetchone()
                if row:
                    return {
                        "email_id": row[0],
                        "classification": row[1],
                        "confidence": row[2],
                        "reason": row[3],
                        "folder_moved_to": row[4],
                        "processed_at": row[5],
                    }
                return None

        except Exception as e:
            logger.error(f"Error finding original classification for content_hash {content_hash}: {e}")
            return None


# Global database manager instance
_db_manager = None


def get_database_manager() -> EmailDatabaseManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = EmailDatabaseManager()
    return _db_manager
