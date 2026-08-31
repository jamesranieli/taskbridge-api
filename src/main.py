"""
TaskBridge API - Project Service

Main FastAPI application entry point.
Initializes database, mounts project routes, and manages application lifecycle.

To run:
    uvicorn src.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.projects.database import init_db, close_db
from src.projects.project_controller import router as projects_router

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle: startup and shutdown.
    
    Startup:
    - Initialize database: create all tables from models
    
    Shutdown:
    - Close database connection pool
    """
    # Startup
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully")
    
    try:
        yield  # Application runs here
    finally:
        # Shutdown
        logger.info("Closing database connections...")
        await close_db()
        logger.info("Database closed successfully")


# Create FastAPI application with lifespan context manager
app = FastAPI(
    title="TaskBridge API",
    description="Project Service",
    version="0.1.0",
    lifespan=lifespan
)

# Mount project routes
app.include_router(projects_router)

logger.info("FastAPI application initialized with Project routes mounted")


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "ok", "service": "taskbridge-api"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
