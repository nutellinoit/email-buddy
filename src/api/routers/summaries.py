"""Daily summaries endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from ...database import get_database_manager

router = APIRouter()


@router.get("/summaries")
def get_summaries(limit: Optional[int] = Query(default=7, ge=1, le=30)):
    db = get_database_manager()
    summaries = db.get_recent_summaries(limit=limit)
    return [s.model_dump() for s in summaries]
