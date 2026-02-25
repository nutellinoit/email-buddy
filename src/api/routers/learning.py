"""Learning endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from ...database import get_database_manager

router = APIRouter()


@router.get("/learning/stats")
def get_learning_stats():
    db = get_database_manager()
    return db.get_learning_statistics()


@router.get("/learning")
def get_learning(
    limit: Optional[int] = Query(default=10, ge=1, le=100),
    days: Optional[int] = Query(default=30, ge=1),
):
    db = get_database_manager()
    return db.get_recent_learning(limit=limit, days=days)
