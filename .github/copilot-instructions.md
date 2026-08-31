# TaskBridge Notification & Audit Service - Copilot Instructions

## Project Overview

**TaskBridge** is a multi-tenant B2B SaaS Notification & Audit Service built to provide secure, scalable notification management and comprehensive audit logging for enterprise clients.

## Technology Stack

- **Framework**: FastAPI (Python 3.9+)
- **ORM**: SQLAlchemy 2.0+ with declarative models
- **Database**: SQLite (development/testing) with migration support for production databases
- **Data Validation**: Pydantic v2 with custom validators
- **Testing**: pytest with pytest-cov for coverage reporting
- **Async**: asyncio with async context managers
- **HTTP Client**: httpx for async HTTP requests
- **Environment**: python-dotenv for configuration management
- **Logging**: Python standard logging with structured JSON output
- **API Documentation**: OpenAPI/Swagger via FastAPI

## Architecture & Layer Pattern

All feature implementations must follow this **Model → Repository → Service → Controller/Route** layered architecture:

### 1. Model Layer (`app/models/`)
- **Responsibility**: Database schema and ORM entity definitions
- **Implementation**:
  - Use SQLAlchemy declarative base classes
  - Include `id` (primary key), `created_at`, `updated_at`, `tenant_id`, and `is_deleted` (soft delete) fields
  - Define relationships with `relationship()` and `back_populates`
  - Use `__tablename__` with snake_case conventions
  - Never include business logic; models are data containers only
  - Define `__repr__` for debugging

**Example structure**:
```python
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(String(1000), nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    tenant = relationship("Tenant", back_populates="notifications")
    user = relationship("User", back_populates="notifications")
    audit_logs = relationship("AuditLog", back_populates="notification")
    
    def __repr__(self):
        return f"<Notification(id={self.id}, tenant_id={self.tenant_id}, status={self.status})>"

````

### 2. Repository Layer (`app/repositories/`)

- **Responsibility**: Data access abstraction and database queries
- **Implementation**:
  - Base `BaseRepository` class with CRUD operations: `create()`, `read()`, `update()`, `delete()`, `list()`
  - Repository per model (e.g., `NotificationRepository`, `AuditLogRepository`)
  - All queries must include tenant isolation (`WHERE tenant_id = :tenant_id`)
  - Soft delete support: queries filter `is_deleted = False` by default
  - Use async/await patterns with `async with db_session`
  - Return None on not found; raise exceptions only for database errors
  - No business logic, only raw queries

**Example structure**:

Python

```
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models import Notification

class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, tenant_id: int, **kwargs) -> Notification:
        notification = Notification(tenant_id=tenant_id, **kwargs)
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification
    
    async def read_by_id(self, tenant_id: int, notification_id: int) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(
                and_(
                    Notification.id == notification_id,
                    Notification.tenant_id == tenant_id,
                    Notification.is_deleted == False
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def list_by_tenant(self, tenant_id: int) -> list[Notification]:
        result = await self.db.execute(
            select(Notification).where(
                and_(
                    Notification.tenant_id == tenant_id,
                    Notification.is_deleted == False
                )
            )
        )
        return result.scalars().all()

```

### 3. Service Layer (`app/services/`)

- **Responsibility**: Business logic, orchestration, and validation
- **Implementation**:
  - Inject repository instances (dependency injection)
  - Handle domain logic, calculations, and workflows
  - Manage transactions and cross-repository operations
  - Raise custom exceptions for business rule violations
  - Call audit logging for all state-changing operations
  - Use type hints extensively; validate inputs
  - No HTTP/web framework knowledge; services are framework-agnostic

**Example structure**:

Python

```
from app.repositories import NotificationRepository
from app.services.audit_service import AuditService
from app.exceptions import NotificationNotFound, InvalidStatusTransition

class NotificationService:
    def __init__(self, notification_repo: NotificationRepository, audit_service: AuditService):
        self.notification_repo = notification_repo
        self.audit_service = audit_service
    
    async def send_notification(self, tenant_id: int, user_id: int, title: str, message: str) -> dict:
        if not title or not message:
            raise ValueError("Title and message are required")
        
        notification = await self.notification_repo.create(
            tenant_id=tenant_id, user_id=user_id, title=title, message=message, status="sent"
        )
        
        await self.audit_service.log_action(
            tenant_id=tenant_id,
            action="notification_sent",
            resource_type="notification",
            resource_id=notification.id,
            user_id=user_id
        )
        
        return {"id": notification.id, "status": notification.status}

```

### 4. Controller/Route Layer (`app/routes/`)

- **Responsibility**: HTTP request handling, response formatting, authentication/authorization
- **Implementation**:
  - Use FastAPI `@app.get()`, `@app.post()`, etc. decorators
  - Inject service instances via FastAPI dependency injection
  - Validate path/query parameters and request body using Pydantic schemas
  - Extract tenant\_id and user\_id from JWT claims or headers
  - Return appropriate HTTP status codes (200, 201, 400, 401, 403, 404, 500)
  - All responses use consistent JSON structure: `{"data": {...}, "error": null}` or `{"data": null, "error": {...}}`
  - Catch service exceptions and translate to appropriate HTTP responses
  - Apply decorators for authentication and authorization checks

**Example structure**:

Python

```
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.services import NotificationService
from app.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/notifications", tags=["notifications"])

class NotificationRequest(BaseModel):
    title: str
    message: str

@router.post("/", status_code=201)
async def create_notification(
    request: NotificationRequest,
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends()
):
    try:
        result = await service.send_notification(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            title=request.title,
            message=request.message
        )
        return {"data": result, "error": None}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

```

---

## Multi-Tenant Data Isolation (Organization-Level)

### Principles

- **Tenant as Isolation Boundary**: Each organization/customer is a distinct tenant
- **Mandatory tenant\_id**: Every data model must include `tenant_id` as a foreign key
- **Query-Level Enforcement**: Every query MUST include `tenant_id` in the WHERE clause
- **No Cross-Tenant Access**: Never return, update, or delete data belonging to another tenant

### Implementation Requirements

1. **Tenant Context**: Extract `tenant_id` from JWT claims, HTTP headers, or request context
2. **Repository Filtering**: Base repository class enforces tenant filtering on all queries
3. **Service Validation**: Services verify tenant\_id matches authenticated user before operations
4. **Route Protection**: Routes extract tenant\_id from authenticated context, never from user input
5. **Audit Trail**: Log all access attempts (including failed ones) for compliance

### Example Tenant Isolation Enforcement

Python

```
# CORRECT: Query includes tenant_id
notification = await repo.read_by_id(tenant_id=current_user.tenant_id, notification_id=123)

# WRONG: Query missing tenant isolation
notification = await db.query(Notification).filter(Notification.id == 123).first()

# CORRECT: Service validates tenant ownership
async def update_notification(self, tenant_id: int, notification_id: int, **kwargs):
    notification = await self.repo.read_by_id(tenant_id, notification_id)
    if not notification:
        raise NotificationNotFound()
    # proceed with update

# WRONG: No tenant validation
async def update_notification(self, notification_id: int, **kwargs):
    notification = await self.repo.read_by_id(notification_id)  # Missing tenant_id!

```

---

## Protection Against Data Exposure

### Sensitive Data Handling

1. **PII Protection**:
   - Never log personally identifiable information (user names, emails, phone numbers)
   - Use placeholders: `user_id={user_id}` instead of `user_email={user.email}`
   - Mask sensitive fields in error responses
2. **Credentials & Secrets**:
   - Never commit API keys, database URLs, or secrets to code
   - Use environment variables via `.env` files (git-ignored)
   - Rotate secrets regularly; document rotation procedures
3. **SQL Injection Prevention**:
   - Always use parameterized queries (SQLAlchemy ORM handles this)
   - Never concatenate user input into SQL strings
   - Validate all inputs at Pydantic schema level
4. **Response Filtering**:
   - Return only fields needed by the client
   - Use Pydantic response schemas to whitelist fields
   - Never return full ORM models directly; serialize via Pydantic

**Example response filtering**:

Python

```
from pydantic import BaseModel

class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    status: str
    created_at: datetime
    
    # Exclude internal fields automatically
    class Config:
        from_attributes = True
        exclude = {"is_deleted", "tenant_id"}

@router.get("/{notification_id}")
async def get_notification(...) -> NotificationResponse:
    notification = await service.get_notification(...)
    return NotificationResponse.model_validate(notification)

```

---

## Input Validation

### Pydantic Schemas

- **All request bodies**: Define Pydantic BaseModel schemas with type hints
- **Field constraints**: Use Field() for min/max length, regex, patterns
- **Custom validators**: Implement @field\_validator for business logic validation
- **Request normalization**: Trim whitespace, convert to lowercase where appropriate

### Validation Rules

1. **Strings**: `str`, max length, allowed characters
2. **Emails**: Use Pydantic's `EmailStr` (requires `email-validator` package)
3. **Enums**: Use Python enums for fixed choice sets
4. **Dates**: Use `datetime`, validate ranges
5. **UUIDs**: Use `UUID` type for unique identifiers
6. **Numbers**: Define `gt=0` (greater than) or `ge=0` (greater or equal) for positive values
7. **Nested Objects**: Use nested Pydantic models for complex structures

**Example validation**:

Python

```
from pydantic import BaseModel, Field, EmailStr, field_validator
from enum import Enum
from typing import Optional

class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"

class NotificationCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Notification title")
    message: str = Field(..., min_length=1, max_length=1000, description="Notification body")
    recipient_email: EmailStr = Field(..., description="Recipient email address")
    status: NotificationStatus = Field(default=NotificationStatus.PENDING)
    retry_count: int = Field(default=0, ge=0, le=5, description="Retry attempts")
    
    @field_validator("title", "message")
    def validate_no_sql_injection(cls, v):
        if any(char in v for char in ["';", "--", "/*"]):
            raise ValueError("Invalid characters detected")
        return v.strip()

# Usage in route
@router.post("/")
async def create(request: NotificationCreateRequest):
    # request is automatically validated
    pass

```

---

## Authentication & Authorization

### Authentication Strategy

- **JWT (JSON Web Tokens)** for stateless authentication
- **Bearer token** in `Authorization: Bearer <token>` header
- **Token claims** include: `user_id`, `tenant_id`, `email`, `roles`, `exp` (expiration)
- **Secret key** stored in environment variable (`AUTH_SECRET_KEY`)

### Authorization Levels

1. **Unauthenticated**: Public endpoints (health check, docs)
2. **Authenticated**: User must provide valid JWT
3. **Tenant-scoped**: User must belong to requested tenant
4. **Role-based**: User must have specific role (admin, user, viewer)

### Implementation

- Dependency injection for current user: `current_user: User = Depends(get_current_user)`
- Role checks: `@require_role("admin")`
- Tenant validation in all state-changing operations

**Example auth pattern**:

Python

```
from fastapi import Depends, HTTPException, status
from jose import JWTError, jwt
from datetime import datetime, timedelta

class User(BaseModel):
    id: int
    email: str
    tenant_id: int
    roles: list[str]

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=["HS256"])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = await user_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def require_role(*allowed_roles):
    async def verify_role(current_user: User = Depends(get_current_user)):
        if not any(role in current_user.roles for role in allowed_roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return verify_role

@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(require_role("admin"))
):
    await service.delete(tenant_id=current_user.tenant_id, id=notification_id)
    return {"data": None, "error": None}

```

---

## Structured Logging

### Logging Configuration

- **Format**: JSON with key-value pairs for machine parsing
- **Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Rotation**: Use RotatingFileHandler for production logs
- **Correlation ID**: Include `request_id` or `trace_id` in all log entries for request tracing

### What to Log

1. **Application Events**: Service calls, database operations, business logic transitions
2. **Security Events**: Authentication attempts, authorization failures, tenant access
3. **Errors**: Stack traces, context, affected resource IDs (not PII)
4. **Performance**: Query execution time, external API calls, duration metrics

### What NOT to Log

- User passwords or API secrets
- Email addresses, phone numbers, or other PII
- Full request/response bodies (log status code, size, relevant headers only)
- Sensitive query parameters

**Example logging**:

Python

```
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Structured log entry
logger.info(json.dumps({
    "timestamp": datetime.utcnow().isoformat(),
    "level": "INFO",
    "event": "notification_created",
    "user_id": user_id,
    "tenant_id": tenant_id,
    "notification_id": notification.id,
    "status": notification.status,
    "duration_ms": elapsed_time
}))

# Error logging
try:
    await service.send_notification(...)
except Exception as e:
    logger.error(json.dumps({
        "timestamp": datetime.utcnow().isoformat(),
        "level": "ERROR",
        "event": "notification_send_failed",
        "user_id": user_id,
        "tenant_id": tenant_id,
        "error_type": type(e).__name__,
        "error_message": str(e),
        "traceback": traceback.format_exc()
    }))
    raise

```

---

## Error Handling

### Custom Exception Hierarchy

All custom exceptions inherit from `BaseException` and include tenant\_id and resource context:

Python

```
class TaskBridgeException(Exception):
    """Base exception for all TaskBridge errors"""
    def __init__(self, message: str, status_code: int = 500, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class ResourceNotFound(TaskBridgeException):
    def __init__(self, resource_type: str, resource_id: int):
        super().__init__(
            message=f"{resource_type} not found",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": resource_id}
        )

class UnauthorizedAccess(TaskBridgeException):
    def __init__(self, message: str = "Unauthorized access"):
        super().__init__(message=message, status_code=403)

class ValidationError(TaskBridgeException):
    def __init__(self, field: str, message: str):
        super().__init__(
            message=f"Validation error: {message}",
            status_code=400,
            details={"field": field, "message": message}
        )

```

### Error Response Format

All error responses follow this structure:

JSON

```
{
    "data": null,
    "error": {
        "type": "ResourceNotFound",
        "message": "Notification not found",
        "status": 404,
        "details": {
            "resource_type": "Notification",
            "resource_id": 123
        }
    }
}

```

### Exception Handling in Routes

Python

```
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from app.exceptions import TaskBridgeException

app = FastAPI()

@app.exception_handler(TaskBridgeException)
async def taskbridge_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "error": {
                "type": exc.__class__.__name__,
                "message": exc.message,
                "status": exc.status_code,
                "details": exc.details
            }
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "error": {
                "type": "InternalServerError",
                "message": "An unexpected error occurred",
                "status": 500
            }
        }
    )

@router.get("/{notification_id}")
async def get_notification(notification_id: int, current_user: User = Depends(get_current_user)):
    try:
        notification = await service.get_notification(current_user.tenant_id, notification_id)
        return {"data": notification, "error": None}
    except ResourceNotFound as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

```

---

## Documentation Expectations

### Code Documentation

1. **Module Docstrings**: Describe module purpose and key responsibilities
2. **Class Docstrings**: Explain class purpose, key methods, and usage examples
3. **Function/Method Docstrings**: Use Google-style format with Args, Returns, Raises sections
4. **Complex Logic**: Inline comments explaining "why", not "what"
5. **Type Hints**: All function signatures must include parameter and return type hints

**Example documentation**:

Python

```
"""
Notification service module.

Handles creation, retrieval, and management of notifications for tenants.
Coordinates with repository and audit service layers.
"""

class NotificationService:
    """Manages notification business logic and orchestration.
    
    This service encapsulates all business rules for notifications including
    creation, status transitions, and retry logic. It coordinates with the
    NotificationRepository for data access and AuditService for logging.
    
    Args:
        notification_repo: Repository instance for notification data access
        audit_service: Service instance for audit logging
    
    Example:
        >>> service = NotificationService(repo, audit_svc)
        >>> result = await service.send_notification(tenant_id=1, user_id=5, ...)
    """
    
    async def send_notification(
        self,
        tenant_id: int,
        user_id: int,
        title: str,
        message: str
    ) -> dict:
        """Send a notification to a user.
        
        Creates a new notification record and initiates the send process.
        Logs audit event for compliance tracking.
        
        Args:
            tenant_id: Organization identifier
            user_id: Target user identifier
            title: Notification title (max 255 chars)
            message: Notification body (max 1000 chars)
        
        Returns:
            Dictionary with notification ID and status
        
        Raises:
            ValueError: If title or message is empty
            DatabaseError: If database operation fails
        
        Example:
            >>> result = await service.send_notification(
            ...     tenant_id=1,
            ...     user_id=5,
            ...     title="Alert",
            ...     message="Your task is due"
            ... )
            >>> print(result["id"])
            42
        """

```

### API Documentation

- FastAPI automatically generates OpenAPI/Swagger docs
- Add descriptions to route parameters: `description="..."`
- Document response schemas with Pydantic models
- Access docs at `/docs` (Swagger) and `/redoc` (ReDoc)

### README Structure

- Project overview and purpose
- Technology stack summary
- Setup and installation instructions
- Environment variables required
- How to run tests
- API endpoint summary with examples
- Contribution guidelines

---

## Testing Standards

### Test Structure

- **Unit Tests**: Test services and repositories in isolation with mocks
- **Integration Tests**: Test full request-response cycle with real database (in-memory SQLite)
- **Test Files**: Colocate with source code: `app/services/notification_service.py` → `tests/services/test_notification_service.py`
- **Coverage Target**: Minimum 80% code coverage for new features

### Testing Patterns

**Unit Test Example**:

Python

```
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services import NotificationService
from app.exceptions import NotificationNotFound

@pytest.fixture
def mock_repo():
    return AsyncMock()

@pytest.fixture
def mock_audit_service():
    return AsyncMock()

@pytest.fixture
def notification_service(mock_repo, mock_audit_service):
    return NotificationService(mock_repo, mock_audit_service)

@pytest.mark.asyncio
async def test_send_notification_success(notification_service, mock_repo, mock_audit_service):
    """Test successful notification creation"""
    # Arrange
    mock_repo.create.return_value = MagicMock(id=1, status="sent")
    
    # Act
    result = await notification_service.send_notification(
        tenant_id=1,
        user_id=5,
        title="Test",
        message="Test message"
    )
    
    # Assert
    assert result["id"] == 1
    mock_repo.create.assert_called_once()
    mock_audit_service.log_action.assert_called_once()

@pytest.mark.asyncio
async def test_send_notification_empty_title_raises_error(notification_service):
    """Test that empty title raises ValueError"""
    with pytest.raises(ValueError):
        await notification_service.send_notification(
            tenant_id=1,
            user_id=5,
            title="",
            message="Valid message"
        )

```

**Integration Test Example**:

Python

```
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.main import app
from app.database import get_db

@pytest.fixture
async def test_db():
    """In-memory SQLite test database"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSession(engine) as session:
        yield session
    
    await engine.dispose()

@pytest.fixture
async def client(test_db):
    """FastAPI test client"""
    async def override_get_db():
        yield test_db
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_create_notification_endpoint(client):
    """Test POST /notifications endpoint"""
    response = await client.post(
        "/notifications/",
        json={"title": "Test", "message": "Test message"},
        headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 201
    assert response.json()["data"]["id"] is not None

```

### Fixture Usage

- **Database**: Use in-memory SQLite for tests
- **Authentication**: Mock JWT tokens or use test credentials
- **External APIs**: Mock with `AsyncMock` or `responses` library
- **Cleanup**: Use pytest fixtures with cleanup in teardown

### Assertion Best Practices

- Use descriptive assertion messages: `assert x == y, "User should have admin role"`
- Test happy path, edge cases, and error paths
- Verify side effects: mock calls, state changes, audit logs
- Test data isolation: verify tenant filtering works correctly

---

## Prompt Recording for Assessment Documentation

### PROMPTS.md Requirement

**This project maintains a complete record of every prompt used during development in ****`PROMPTS.md`**** for assessment documentation.**

### Recording Format

Each prompt entry must include:

1. **Timestamp**: When the prompt was given (ISO 8601 format)
2. **Session ID**: Optional correlation ID or session identifier
3. **Prompt Category**: Type of request (e.g., "Feature Implementation", "Bug Fix", "Testing", "Documentation")
4. **Prompt Text**: Complete, unmodified prompt as given to GitHub Copilot
5. **Context**: Brief description of what was being worked on
6. **Files Modified**: List of files created or modified
7. **Outcome**: Brief summary of result (success, partial, iteration required)

### Example PROMPTS.md Entry

Markdown

```
## Prompt #1: Initial Project Setup

**Timestamp**: 2026-08-31T10:00:00Z  
**Category**: Project Setup  
**Context**: Initialize TaskBridge FastAPI project structure

**Prompt**:
> Create the basic FastAPI project structure for TaskBridge Notification & Audit Service with:
> - main.py entry point
> - app/models/__init__.py for SQLAlchemy models
> - app/repositories/__init__.py for data access layer
> - app/services/__init__.py for business logic
> - app/routes/__init__.py for API endpoints
> - app/database.py for database configuration
> - requirements.txt with all dependencies

**Files Created**:
- main.py
- app/__init__.py
- app/models/__init__.py
- app/repositories/__init__.py
- app/services/__init__.py
- app/routes/__init__.py
- app/database.py
- requirements.txt

**Outcome**: ✅ Success - Project structure initialized with all layers in place

---

```

### Recording Instructions for Copilot

- **Record every prompt**: Log all requests, including follow-ups and iterations
- **Exact prompt text**: Copy the complete prompt without modification
- **Incremental updates**: Append new prompts to PROMPTS.md as they occur
- **Timestamp accuracy**: Use current UTC time in ISO 8601 format
- **Link files**: Reference all modified/created files for traceability
- **Assessment value**: This record demonstrates decision-making, iteration cycles, and problem-solving approach

---

## Summary: Coding Standards & Best Practices

### Code Organization

- Follow Model → Repository → Service → Route layer pattern strictly
- Keep files focused and single-responsibility
- Use type hints everywhere
- Async/await for all I/O operations

### Naming Conventions

- **Files/Directories**: snake\_case (e.g., `notification_service.py`)
- **Classes**: PascalCase (e.g., `NotificationService`)
- **Functions/Methods**: snake\_case (e.g., `send_notification()`)
- **Constants**: UPPER\_SNAKE\_CASE (e.g., `MAX_RETRIES = 5`)
- **Database tables**: snake\_case, plural (e.g., `notifications`)

### Code Quality

- **No hardcoded values**: Use environment variables or config files
- **DRY principle**: Extract common logic to utility functions
- **Error handling**: Never silently catch exceptions; always handle appropriately
- **Async context**: Always use context managers: `async with db_session as session:`
- **Database transactions**: Commit/rollback appropriately in repository layer

### Dependencies & Imports

- Group imports: standard library, third-party, local (in that order)
- Use absolute imports: `from app.services import NotificationService`
- Avoid circular imports by respecting layer boundaries

### Performance Considerations

- Use database indexes on frequently queried columns (tenant\_id, user\_id, created\_at)
- Implement pagination for list endpoints
- Cache read-only data when appropriate
- Monitor and optimize N+1 query problems with SQLAlchemy eager loading

---

## Getting Started with Copilot

When using GitHub Copilot for this project:

1. **Provide context**: Reference the layer (e.g., "In the repository layer...")
2. **Be specific**: "Create a Service class that..."
3. **Request patterns**: Ask for example implementations before full features
4. **Testing first**: Request test cases before implementation when appropriate
5. **Record prompts**: After each session, ensure PROMPTS.md is updated
6. **Review suggestions**: Copilot suggestions must align with this guide; reject and rephrase if needed