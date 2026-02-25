"""
Database models for Email-Buddy email tracking system.
"""

import hashlib
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class ProcessedEmail(BaseModel):
    """Model for a processed email record."""

    model_config = ConfigDict(from_attributes=True)

    email_id: str
    message_id: str
    subject: str
    sender: str
    date_received: str
    classification: str
    confidence: float
    reason: str
    folder_moved_to: Optional[str]
    processed_at: str
    content_hash: str
    backup_path: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def from_email_data(
        cls,
        email_data: Dict[str, Any],
        classification: str,
        confidence: float,
        reason: str,
        folder_moved_to: Optional[str] = None,
        backup_path: Optional[str] = None,
    ) -> "ProcessedEmail":
        """Create ProcessedEmail from email data and classification results."""
        # Use content_id as primary identifier, fallback to content_hash generation
        if "content_id" in email_data:
            content_hash = email_data["content_id"]
            email_id = email_data["content_id"]
        else:
            # Fallback: generate content hash for backward compatibility
            content_for_hash = (
                f"{email_data.get('subject', '')}{email_data.get('sender', '')}{email_data.get('body', '')}"
            )
            content_hash = hashlib.md5(content_for_hash.encode("utf-8"), usedforsecurity=False).hexdigest()
            email_id = content_hash

        return cls(
            email_id=email_id,
            message_id=email_data.get("message_id", ""),
            subject=email_data.get("subject", ""),
            sender=email_data.get("sender", ""),
            date_received=email_data.get("date", ""),
            classification=classification,
            confidence=confidence,
            reason=reason,
            folder_moved_to=folder_moved_to,
            processed_at=datetime.now().isoformat(),
            content_hash=content_hash,
            backup_path=backup_path,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return self.model_dump(exclude={"id"})

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ProcessedEmail":
        """Create ProcessedEmail from SQLite row."""
        # backup_path may not exist in older databases
        try:
            backup_path = row["backup_path"]
        except (IndexError, KeyError):
            backup_path = None

        return cls(
            id=row["id"],
            email_id=row["email_id"],
            message_id=row["message_id"],
            subject=row["subject"],
            sender=row["sender"],
            date_received=row["date_received"],
            classification=row["classification"],
            confidence=row["confidence"],
            reason=row["reason"],
            folder_moved_to=row["folder_moved_to"],
            processed_at=row["processed_at"],
            content_hash=row["content_hash"],
            backup_path=backup_path,
        )


class LearningData(BaseModel):
    """Model for learning data from user corrections."""

    model_config = ConfigDict(from_attributes=True)

    message_id: str
    source_folder: str
    target_classification: str
    learning_type: str
    email_subject: str
    email_sender: str
    email_domain: str
    sender_type: Optional[str] = None
    content_type: Optional[str] = None
    learning_summary: str
    confidence_score: float = 1.0
    created_at: str
    id: Optional[int] = None

    @classmethod
    def from_email_data(
        cls,
        email_data: Dict[str, Any],
        source_folder: str,
        target_classification: str,
        learning_summary: str,
        confidence_score: float = 1.0,
    ) -> "LearningData":
        """Create LearningData from email data and learning results."""
        sender = email_data.get("sender", "")
        email_domain = ""
        if "@" in sender:
            try:
                email_domain = sender.split("@")[1].split(">")[0].strip()
            except Exception:
                email_domain = ""

        # Determine learning type based on source and target
        learning_type = cls._determine_learning_type(source_folder, target_classification)

        return cls(
            message_id=email_data.get("message_id", ""),
            source_folder=source_folder,
            target_classification=target_classification,
            learning_type=learning_type,
            email_subject=email_data.get("subject", ""),
            email_sender=sender,
            email_domain=email_domain,
            learning_summary=learning_summary,
            confidence_score=confidence_score,
            created_at=datetime.now().isoformat(),
        )

    @staticmethod
    def _determine_learning_type(source_folder: str, target_classification: str) -> str:
        """Determine the learning type based on source folder and target classification."""
        from .config import config

        # Build reverse map: folder -> category name
        folder_to_category = {}
        for cat in config.CATEGORIES:
            if cat.folder:
                folder_to_category[cat.folder] = cat.name
        # INBOX maps to the default category
        folder_to_category[config.INBOX_FOLDER] = config.default_category.name

        source_category = folder_to_category.get(source_folder)
        default_name = config.default_category.name

        if source_category and source_category != target_classification:
            if target_classification == default_name:
                return f"false_positive_{source_category}"
            elif source_category == default_name:
                return f"false_negative_{target_classification}"
            else:
                return f"{source_category}_to_{target_classification}"
        return "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return self.model_dump(exclude={"id"})

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "LearningData":
        """Create LearningData from SQLite row."""
        return cls(
            id=row["id"],
            message_id=row["message_id"],
            source_folder=row["source_folder"],
            target_classification=row["target_classification"],
            learning_type=row["learning_type"],
            email_subject=row["email_subject"],
            email_sender=row["email_sender"],
            email_domain=row["email_domain"],
            sender_type=row["sender_type"],
            content_type=row["content_type"],
            learning_summary=row["learning_summary"],
            confidence_score=row["confidence_score"],
            created_at=row["created_at"],
        )


class DailySummary(BaseModel):
    """Model for a daily summary record."""

    model_config = ConfigDict(from_attributes=True)

    generated_at: str
    period_start: str
    period_end: str
    total_processed: int
    stats_json: str
    narrative: Optional[str] = None
    delivered: bool = False
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DailySummary":
        """Create DailySummary from SQLite row."""
        return cls(
            id=row["id"],
            generated_at=row["generated_at"],
            period_start=row["period_start"],
            period_end=row["period_end"],
            total_processed=row["total_processed"],
            stats_json=row["stats_json"],
            narrative=row["narrative"],
            delivered=bool(row["delivered"]),
        )


class EmailDatabase:
    """Database schema and setup for email tracking."""

    CREATE_PROCESSED_EMAILS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS processed_emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_id TEXT NOT NULL,
        message_id TEXT,
        subject TEXT,
        sender TEXT,
        date_received TEXT,
        classification TEXT NOT NULL,
        confidence REAL NOT NULL,
        reason TEXT,
        folder_moved_to TEXT,
        processed_at TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        backup_path TEXT,
        UNIQUE(email_id, message_id, content_hash)
    );
    """

    CREATE_LEARNING_DATA_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS learning_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        source_folder TEXT NOT NULL,
        target_classification TEXT NOT NULL,
        learning_type TEXT NOT NULL,
        email_subject TEXT,
        email_sender TEXT,
        email_domain TEXT,
        sender_type TEXT,
        content_type TEXT,
        learning_summary TEXT NOT NULL,
        confidence_score REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL
    );
    """

    CREATE_DAILY_SUMMARIES_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS daily_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generated_at TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        total_processed INTEGER NOT NULL,
        stats_json TEXT NOT NULL,
        narrative TEXT,
        delivered INTEGER NOT NULL DEFAULT 0
    );
    """

    CREATE_INDEXES_SQL = [
        # Processed emails indexes
        "CREATE INDEX IF NOT EXISTS idx_email_id ON processed_emails(email_id);",
        "CREATE INDEX IF NOT EXISTS idx_message_id ON processed_emails(message_id);",
        "CREATE INDEX IF NOT EXISTS idx_content_hash ON processed_emails(content_hash);",
        "CREATE INDEX IF NOT EXISTS idx_classification ON processed_emails(classification);",
        "CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_emails(processed_at);",
        # Learning data indexes
        "CREATE INDEX IF NOT EXISTS idx_learning_message_id ON learning_data(message_id);",
        "CREATE INDEX IF NOT EXISTS idx_learning_type ON learning_data(learning_type);",
        "CREATE INDEX IF NOT EXISTS idx_learning_source_folder ON learning_data(source_folder);",
        "CREATE INDEX IF NOT EXISTS idx_learning_target_classification ON learning_data(target_classification);",
        "CREATE INDEX IF NOT EXISTS idx_learning_created_at ON learning_data(created_at);",
        "CREATE INDEX IF NOT EXISTS idx_learning_email_domain ON learning_data(email_domain);",
        # Daily summaries indexes
        "CREATE INDEX IF NOT EXISTS idx_summary_generated_at ON daily_summaries(generated_at);",
    ]

    @classmethod
    def init_database(cls, db_path: str) -> None:
        """Initialize the database with required tables and indexes."""
        with sqlite3.connect(db_path) as conn:
            # Create tables
            conn.execute(cls.CREATE_PROCESSED_EMAILS_TABLE_SQL)
            conn.execute(cls.CREATE_LEARNING_DATA_TABLE_SQL)
            conn.execute(cls.CREATE_DAILY_SUMMARIES_TABLE_SQL)

            # Migration: add backup_path column to processed_emails
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(processed_emails)")
            columns = {row[1] for row in cursor.fetchall()}
            if "backup_path" not in columns:
                cursor.execute("ALTER TABLE processed_emails ADD COLUMN backup_path TEXT")
                conn.commit()

            # Migration: remove UNIQUE(message_id) from learning_data
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='learning_data'")
            row = cursor.fetchone()
            if row and 'UNIQUE(message_id)' in row[0]:
                cursor.execute("ALTER TABLE learning_data RENAME TO learning_data_old")
                cursor.execute(cls.CREATE_LEARNING_DATA_TABLE_SQL)
                cursor.execute("INSERT INTO learning_data SELECT * FROM learning_data_old")
                cursor.execute("DROP TABLE learning_data_old")
                conn.commit()

            # Create indexes
            for index_sql in cls.CREATE_INDEXES_SQL:
                conn.execute(index_sql)

            conn.commit()

    @classmethod
    def get_connection(cls, db_path: str) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
