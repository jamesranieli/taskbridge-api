"""
Pydantic schemas for Project API requests and responses.

Schemas define the API contract for project operations, including:
- Input validation (via Pydantic field validators)
- Type hints for OpenAPI/Swagger documentation
- Consistent response structures
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ProjectCreateRequest(BaseModel):
    """Request schema for creating a new project."""
    
    name: str = Field(..., min_length=1, max_length=255, description="Project name (required, 1-255 chars)")
    description: Optional[str] = Field(None, max_length=10000, description="Optional project description (max 10000 chars)")
    
    @field_validator('name')
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        """Ensure name is not only whitespace."""
        if not v or not v.strip():
            raise ValueError("Project name cannot be empty")
        return v.strip()
    
    @field_validator('description', mode='before')
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Strip description whitespace; allow None."""
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class ProjectStatusUpdateRequest(BaseModel):
    """Request schema for updating project status."""
    
    status: str = Field(..., description="New project status (active, archived, or inactive)")
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status is one of allowed values."""
        valid_statuses = {"active", "archived", "inactive"}
        if v not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}")
        return v


class ProjectResponse(BaseModel):
    """Response schema for a project (read-only ORM model representation)."""
    
    id: int = Field(..., description="Project ID")
    tenant_id: int = Field(..., description="Tenant ID (organization)")
    team_id: int = Field(..., description="Team ID (team ownership)")
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    status: str = Field(..., description="Project status (active, archived, inactive)")
    created_at: datetime = Field(..., description="UTC timestamp when project was created")
    updated_at: datetime = Field(..., description="UTC timestamp of last modification")
    
    class Config:
        """Pydantic config for ORM model compatibility."""
        from_attributes = True  # Allow conversion from SQLAlchemy ORM objects


class PaginatedProjectsResponse(BaseModel):
    """Response schema for paginated project listings."""
    
    data: list[ProjectResponse] = Field(..., description="List of projects")
    total: int = Field(..., description="Total count of projects (across all pages)")
    limit: int = Field(..., description="Items per page (used in this request)")
    offset: int = Field(..., description="Items skipped (used in this request)")
    
    class Config:
        """Pydantic config for ORM model compatibility."""
        from_attributes = True
