"""
Database configuration and ORM setup for TaskBridge projects module.

This module provides:
- SQLAlchemy declarative base for ORM models
- Async engine and session factory for database connections
- FastAPI dependency for injecting AsyncSession into routes

Database:
- Uses file-backed SQLite for persistent storage
- Suitable for standalone development/testing of projects service
- Future: Will be refactored when app.database is created for production deployment

Session Management:
- Async sessions via SQLAlchemy's AsyncSession
- FastAPI dependency injection via get_db()
- Automatic rollback and session cleanup on exceptions
"""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# ORM declarative base - all models in this package inherit from this
Base = declarative_base()

# Database URL: file-backed SQLite for persistence
# Location: .data/projects.db relative to repository root
# TODO: Move to environment variables or config module for production
DATABASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".data")
os.makedirs(DATABASE_DIR, exist_ok=True)
DATABASE_URL = f"sqlite+aiosqlite:///{os.path.join(DATABASE_DIR, 'projects.db')}"

# Create async engine with connection pooling
# pool_pre_ping=True verifies connections before using them
# echo=False disables SQL logging (set to True for debugging)
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

# Create async session factory
# expire_on_commit=False keeps ORM objects usable after commit
# autoflush=False requires explicit flush() for database visibility
SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an AsyncSession for route handlers.
    
    Usage in routes:
        @router.get("/projects")
        async def list_projects(db: AsyncSession = Depends(get_db)):
            service = ProjectService(db)
            ...
    
    The session is automatically closed when the route handler completes.
    If an exception occurs, changes are automatically rolled back.
    
    Yields:
        AsyncSession: Database session for the request lifetime
    """
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database: create all tables defined in Base.metadata.
    
    Call this once at application startup:
        await init_db()
    
    In production, use Alembic for schema migrations instead.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close the engine connection pool.
    
    Call this at application shutdown:
        await close_db()
    """
    await engine.dispose()
