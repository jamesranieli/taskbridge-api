"""
Project API controller/router.

Provides HTTP endpoints for project management:
- POST /tenants/{tenant_id}/teams/{team_id}/projects: Create a new project
- PATCH /tenants/{tenant_id}/teams/{team_id}/projects/{project_id}/status: Update project status
- GET /tenants/{tenant_id}/teams/{team_id}/projects: List projects by team (with pagination)
- DELETE /tenants/{tenant_id}/teams/{team_id}/projects/{project_id}: Delete a project

Enforces tenant_id and team_id isolation at the API boundary.
Maps service-layer exceptions to appropriate HTTP responses.
Returns generic not-found/access-denied responses to avoid leaking cross-team information.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Query, Path, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .project_schemas import (
    ProjectCreateRequest,
    ProjectStatusUpdateRequest,
    ProjectResponse,
    PaginatedProjectsResponse,
)
from .project_service import (
    ProjectService,
    ProjectNotFoundError,
    InvalidProjectStatusError,
)
from .project_repository import ProjectDataError, RepositoryError

logger = logging.getLogger(__name__)

# Router configuration
router = APIRouter(prefix="/api/v1", tags=["projects"])


# ==================== ENDPOINTS ====================

@router.post(
    "/tenants/{tenant_id}/teams/{team_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
    responses={
        201: {"description": "Project created successfully"},
        400: {"description": "Invalid input (missing/empty name, description too long)"},
        500: {"description": "Database error"},
    },
)
async def create_project(
    tenant_id: Annotated[int, Path(..., gt=0, description="Tenant ID (organization)")],
    team_id: Annotated[int, Path(..., gt=0, description="Team ID (project owner)")],
    request: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """
    Create a new project for a team.
    
    **Path Parameters:**
    - `tenant_id`: Tenant ID for multi-tenant isolation
    - `team_id`: Team that owns the project
    
    **Request Body:**
    - `name`: Project name (1-255 chars, required)
    - `description`: Optional project description (max 10000 chars)
    
    **Returns:** Created project with auto-assigned ID and "active" status
    
    **Note:** Caller is responsible for validating that tenant_id and team_id are valid
    and that team_id belongs to tenant_id. Service-layer isolation prevents cross-team
    mutations but does not validate team/tenant existence or ownership.
    """
    service = ProjectService(db)
    
    try:
        project = await service.create_project(
            tenant_id=tenant_id,
            team_id=team_id,
            name=request.name,
            description=request.description,
        )
        logger.info(
            "Project created via API",
            extra={"project_id": project.id, "tenant_id": tenant_id, "team_id": team_id},
        )
        return ProjectResponse.model_validate(project)
    
    except ValueError as e:
        logger.warning(f"Project creation validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    except ProjectDataError as e:
        logger.error(f"Project creation database error: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project due to database error",
        )
    
    except RepositoryError as e:
        logger.error(f"Repository error creating project: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed",
        )


@router.patch(
    "/tenants/{tenant_id}/teams/{team_id}/projects/{project_id}/status",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update project status",
    responses={
        200: {"description": "Project status updated successfully"},
        400: {"description": "Invalid status or invalid state transition"},
        403: {"description": "Project not found or access denied"},
        500: {"description": "Database error"},
    },
)
async def update_project_status(
    tenant_id: Annotated[int, Path(..., gt=0, description="Tenant ID (organization)")],
    team_id: Annotated[int, Path(..., gt=0, description="Team ID (project owner)")],
    project_id: Annotated[int, Path(..., gt=0, description="Project ID")],
    request: ProjectStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    """
    Update a project's status with state-transition validation.
    
    **Path Parameters:**
    - `tenant_id`: Tenant ID for multi-tenant isolation
    - `team_id`: Team that owns the project
    - `project_id`: Project to update
    
    **Request Body:**
    - `status`: New status (active, archived, or inactive)
    
    **Valid Transitions:**
    - active → archived, inactive
    - archived → active
    - inactive → active
    
    **Returns:** Updated project with new status
    
    **Note:** Returns 403 (not 404) for not-found/access-denied to avoid leaking team information.
    """
    service = ProjectService(db)
    
    try:
        project = await service.update_status(
            tenant_id=tenant_id,
            team_id=team_id,
            project_id=project_id,
            new_status=request.status,
        )
        logger.info(
            "Project status updated via API",
            extra={
                "project_id": project_id,
                "tenant_id": tenant_id,
                "team_id": team_id,
                "new_status": request.status,
            },
        )
        return ProjectResponse.model_validate(project)
    
    except ProjectNotFoundError:
        logger.warning(
            "Project not found or access denied",
            extra={"project_id": project_id, "team_id": team_id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project not found or access denied",
        )
    
    except InvalidProjectStatusError as e:
        logger.warning(f"Invalid status transition: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    except RepositoryError as e:
        logger.error(f"Repository error updating project status: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed",
        )


@router.get(
    "/tenants/{tenant_id}/teams/{team_id}/projects",
    response_model=PaginatedProjectsResponse,
    status_code=status.HTTP_200_OK,
    summary="List projects by team",
    responses={
        200: {"description": "Projects retrieved successfully"},
        400: {"description": "Invalid pagination parameters"},
        500: {"description": "Database error"},
    },
)
async def list_projects_by_team(
    tenant_id: Annotated[int, Path(..., gt=0, description="Tenant ID (organization)")],
    team_id: Annotated[int, Path(..., gt=0, description="Team ID (project owner)")],
    limit: Annotated[int, Query(default=20, ge=1, le=1000, description="Results per page")] = 20,
    offset: Annotated[int, Query(default=0, ge=0, description="Results to skip")] = 0,
    db: AsyncSession = Depends(get_db),
) -> PaginatedProjectsResponse:
    """
    List all projects for a team with pagination.
    
    **Path Parameters:**
    - `tenant_id`: Tenant ID for multi-tenant isolation
    - `team_id`: Team to list projects for
    
    **Query Parameters:**
    - `limit`: Results per page (1-1000, default 20)
    - `offset`: Results to skip for pagination (default 0)
    
    **Returns:** Paginated list of projects ordered by creation date (newest first)
    
    **Note:** Only returns non-deleted projects. Total count excludes pagination limits.
    """
    service = ProjectService(db)
    
    try:
        projects, total_count = await service.list_projects_by_team(
            tenant_id=tenant_id,
            team_id=team_id,
            limit=limit,
            offset=offset,
        )
        logger.debug(
            "Projects listed via API",
            extra={
                "tenant_id": tenant_id,
                "team_id": team_id,
                "limit": limit,
                "offset": offset,
                "count": len(projects),
                "total": total_count,
            },
        )
        return PaginatedProjectsResponse(
            data=[ProjectResponse.model_validate(p) for p in projects],
            total=total_count,
            limit=limit,
            offset=offset,
        )
    
    except ValueError as e:
        logger.warning(f"Invalid pagination parameters: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    except RepositoryError as e:
        logger.error(f"Repository error listing projects: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed",
        )


@router.delete(
    "/tenants/{tenant_id}/teams/{team_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    responses={
        204: {"description": "Project deleted successfully"},
        403: {"description": "Project not found or access denied"},
        500: {"description": "Database error"},
    },
)
async def delete_project(
    tenant_id: Annotated[int, Path(..., gt=0, description="Tenant ID (organization)")],
    team_id: Annotated[int, Path(..., gt=0, description="Team ID (project owner)")],
    project_id: Annotated[int, Path(..., gt=0, description="Project ID")],
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Soft delete a project.
    
    **Path Parameters:**
    - `tenant_id`: Tenant ID for multi-tenant isolation
    - `team_id`: Team that owns the project
    - `project_id`: Project to delete
    
    **Returns:** 204 No Content on success
    
    **Note:**
    - Soft delete preserves data for compliance and audit purposes
    - Project is hidden from list operations but can be restored
    - Returns 403 (not 404) for not-found/access-denied to avoid leaking team information
    """
    service = ProjectService(db)
    
    try:
        await service.delete_project(
            tenant_id=tenant_id,
            team_id=team_id,
            project_id=project_id,
        )
        logger.info(
            "Project deleted via API",
            extra={"project_id": project_id, "tenant_id": tenant_id, "team_id": team_id},
        )
    
    except ProjectNotFoundError:
        logger.warning(
            "Project not found or access denied",
            extra={"project_id": project_id, "team_id": team_id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project not found or access denied",
        )
    
    except RepositoryError as e:
        logger.error(f"Repository error deleting project: {str(e)}", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed",
        )
