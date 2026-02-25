"""System endpoints: health check and configuration."""

import os

from fastapi import APIRouter

from ...config import config

router = APIRouter()


@router.get("/health")
def health():
    db_exists = os.path.exists(config.DATABASE_PATH)
    return {
        "status": "ok" if db_exists else "degraded",
        "database": config.DATABASE_PATH,
        "database_exists": db_exists,
    }


@router.get("/config")
def get_config():
    return {
        "categories": [
            {
                "name": c.name,
                "folder": c.folder,
                "threshold": c.threshold,
                "description": c.description,
                "is_default": c.is_default,
            }
            for c in config.CATEGORIES
        ],
        "llm_model": config.LITELLM_MODEL,
        "process_interval": config.PROCESS_INTERVAL,
        "idle_enabled": config.IDLE_ENABLED,
        "email_limit": config.EMAIL_LIMIT,
        "email_fetch_days": config.EMAIL_FETCH_DAYS,
        "dry_run": config.DRY_RUN,
        "learning_enabled": config.LEARNING_ENABLED,
        "learning_retention_days": config.LEARNING_RETENTION_DAYS,
        "daily_summary_enabled": config.DAILY_SUMMARY_ENABLED,
        "daily_summary_hour": config.DAILY_SUMMARY_HOUR,
        "email_retention_days": config.EMAIL_RETENTION_DAYS,
    }
