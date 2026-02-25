"""Email endpoints."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from ...database import get_database_manager

router = APIRouter()


@router.get("/emails")
def get_emails(
    limit: Optional[int] = Query(default=50, ge=1, le=500),
    classification: Optional[str] = Query(default=None),
):
    db = get_database_manager()
    emails = db.get_processed_emails(limit=limit, classification=classification)
    return [e.model_dump() for e in emails]


@router.get("/emails/recent")
def get_recent_emails(
    hours: Optional[int] = Query(default=24, ge=1),
    limit: Optional[int] = Query(default=20, ge=1, le=200),
):
    db = get_database_manager()
    since = datetime.now() - timedelta(hours=hours)
    emails = db.get_recent_email_details_since(since, limit=limit)
    return [e.model_dump() for e in emails]
