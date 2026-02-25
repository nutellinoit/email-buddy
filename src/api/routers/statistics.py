"""Statistics endpoints."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from ...database import get_database_manager

router = APIRouter()


@router.get("/stats")
def get_statistics():
    db = get_database_manager()
    return db.get_statistics()


@router.get("/stats/since")
def get_statistics_since(hours: Optional[int] = Query(default=24, ge=1)):
    db = get_database_manager()
    since = datetime.now() - timedelta(hours=hours)
    return db.get_summary_statistics_since(since)


@router.get("/stats/timeline")
def get_classification_timeline(hours: Optional[int] = Query(default=168, ge=1)):
    db = get_database_manager()
    since = datetime.now() - timedelta(hours=hours)
    bucket_size = 1 if hours <= 24 else 24
    return db.get_classification_timeline(since, bucket_size_hours=bucket_size)
