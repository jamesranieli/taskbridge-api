"""
Pytest configuration and shared fixtures for Project Service tests.

All tests use an isolated in-memory SQLite database.
Production database .data/projects.db is not affected by test execution.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from httpx import AsyncClient
from contextlib import asynccontextmanager

from src.projects.database import Base
# Import Project model to register it with SQLAlchemy metadata before create_all()
from src.projects.project import Project


@pytest_asyncio.fixture
async def test_db_engine():
    """
    Create an isolated in-memory SQLite database for testing.
    
    Automatically creates all tables from Base.metadata.
    Database is completely isolated from production .data/projects.db.
    
    Note: Project model must be imported before this fixture runs to ensure
    the projects table is registered in SQLAlchemy metadata.
    """
    test_database_url = "sqlite+aiosqlite:///:memory:"
    
    engine = create_async_engine(
        test_database_url,
        echo=False,
        future=True,
    )
    
    # Create all tables from ORM models (Project table included)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Cleanup
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(test_db_engine):
    """
    Provide an AsyncSession connected to test database.
    
    Yields a fresh session for each test.
    """
    SessionLocal = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def test_app(test_db_session):
    """
    Create a FastAPI app with test database context.
    
    CRITICAL: This fixture creates an isolated FastAPI application instance
    for testing the Project API routes. It does NOT use the production app
    from src.main, which has a lifespan that initializes the production
    database. Instead:
    
    1. Create a new FastAPI app instance with a test-safe lifespan (no-op)
    2. Mount the Project router directly
    3. Override get_db to use test_db_session
    
    This ensures:
    - Production .data/projects.db is never accessed during tests
    - The real Project router logic is tested
    - Database dependency injection is overridden for isolation
    
    The production app's lifespan runs only when an ASGI server starts the
    application (not during import).
    """
    from fastapi import FastAPI
    from src.projects.project_controller import router as projects_router
    from src.projects.database import get_db
    
    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        """Test lifespan: no startup/shutdown, just yield."""
        yield
    
    # Create new app with test lifespan (no init_db, no close_db)
    test_app_instance = FastAPI(
        title="TaskBridge API Test",
        description="Project Service (Test)",
        version="0.1.0",
        lifespan=test_lifespan
    )
    
    # Mount the real Project router
    test_app_instance.include_router(projects_router)
    
    # Override get_db dependency to use test database session
    async def override_get_db():
        yield test_db_session
    
    test_app_instance.dependency_overrides[get_db] = override_get_db
    
    return test_app_instance


@pytest_asyncio.fixture
async def test_client(test_app):
    """
    Provide FastAPI AsyncClient with test app and isolated database.
    
    Uses the test_app fixture which:
    - Has a no-op test lifespan (does not initialize production database)
    - Mounts the real Project router
    - Overrides get_db to use test database
    """
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        yield client


# ==================== Test Data Fixtures ====================

@pytest.fixture
def valid_project_create():
    """Valid project creation data."""
    return {
        "name": "Test Project",
        "description": "A test project"
    }


@pytest.fixture
def valid_project_minimal():
    """Minimal valid project (no description)."""
    return {
        "name": "Minimal Project"
    }
