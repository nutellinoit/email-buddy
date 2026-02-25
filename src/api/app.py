"""
FastAPI read-only API for Email-Buddy web dashboard.
Runs as a daemon thread alongside the main email processing loop.
"""

import logging
import threading

from fastapi import FastAPI

from .routers import emails, learning, statistics, summaries, system

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Email-Buddy API",
    description="Read-only API for the Email-Buddy web dashboard",
    version="1.0.0",
)

app.include_router(system.router, prefix="/api", tags=["system"])
app.include_router(statistics.router, prefix="/api", tags=["statistics"])
app.include_router(emails.router, prefix="/api", tags=["emails"])
app.include_router(learning.router, prefix="/api", tags=["learning"])
app.include_router(summaries.router, prefix="/api", tags=["summaries"])


def start_api_server(host: str = "0.0.0.0", port: int = 8000) -> None:  # nosec B104
    """Start the FastAPI server in a daemon thread."""
    import uvicorn

    def _run():
        uvicorn.run(app, host=host, port=port, log_level="warning")

    thread = threading.Thread(target=_run, daemon=True, name="api-server")
    thread.start()
    logger.info(f"API server started on {host}:{port}")
