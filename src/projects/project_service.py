"""
Service layer for Project business logic.

Enforces business rules, validation, and multi-tenant isolation.
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .project import Project
from .project_repository import ProjectRepository, ProjectDataError, RepositoryError
from .exceptions import ProjectNotFoundError, InvalidProjectStatusError, ProjectValidationError

logger = logging.getLogger(__name__)


class ProjectService:
    """
    Service layer for Project CRUD and status management.
    
    Enforces:
    - Input validation (name, description length)
    - Multi-tenant isolation (tenant_id on all operations)
    - Team-based authorization (tenant_id + team_id)
    - Status transition rules
    """
    
    VALID_STATUSES = frozenset(["active", "archived", "inactive"])
    VALID_TRANSITIONS = {
        "active": ["archived", "inactive"],
        "archived": ["active"],
        "inactive": ["active"]
    }
    MAX_NAME_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 10000
    
    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session."""
        self.db = db
        self.repository = ProjectRepository(db)
    
    async def create_project(
        self,
        tenant_id: int,
        team_id: int,
        name: str,
        description: Optional[str] = None
    ) -> Project:
        """
        Create a new project.
        
        Args:
            tenant_id: Tenant (organization) ID
            team_id: Team ID that owns the project
            name: Project name (1-255 chars, required)
            description: Optional description (max 10000 chars)
        
        Returns:
            Created Project instance
        
        Raises:
            ProjectValidationError: If input validation fails
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        """
        # Validate input
        if not name or not name.strip():
            raise ProjectValidationError("Project name cannot be empty")
        
        name_stripped = name.strip()
        if len(name_stripped) > self.MAX_NAME_LENGTH:
            raise ProjectValidationError(
                f"Project name must be {self.MAX_NAME_LENGTH} characters or less"
            )
        
        description_stripped = None
        if description:
            description_stripped = description.strip()
            if description_stripped and len(description_stripped) > self.MAX_DESCRIPTION_LENGTH:
                raise ProjectValidationError(
                    f"Project description must be {self.MAX_DESCRIPTION_LENGTH} characters or less"
                )
        
        try:
            async with self.db.begin():
                project = await self.repository.create(
                    tenant_id=tenant_id,
                    team_id=team_id,
                    name=name_stripped,
                    description=description_stripped,
                    status="active"
                )
                logger.info(
                    "Project created",
                    extra={
                        "tenant_id": tenant_id,
                        "team_id": team_id,
                        "project_id": project.id,
                        "name": name_stripped
                    }
                )
                return project
        except (ProjectDataError, RepositoryError) as e:
            logger.error(
                "Failed to create project",
                extra={"tenant_id": tenant_id, "team_id": team_id, "name": name_stripped},
                exc_info=e
            )
            raise
    
    async def get_project(self, tenant_id: int, project_id: int) -> Project:
        """
        Get a project by ID (tenant-scoped).
        
        Args:
            tenant_id: Tenant ID for isolation
            project_id: Project ID to retrieve
        
        Returns:
            Project instance
        
        Raises:
            ProjectNotFoundError: If project not found
            RepositoryError: If database query fails
        """
        try:
            project = await self.repository.read_by_id(tenant_id, project_id)
            if not project:
                raise ProjectNotFoundError("Project not found")
            
            logger.debug(
                "Retrieved project",
                extra={"tenant_id": tenant_id, "project_id": project_id}
            )
            return project
        except RepositoryError as e:
            logger.error(
                "Failed to retrieve project",
                extra={"tenant_id": tenant_id, "project_id": project_id},
                exc_info=e
            )
            raise
    
    async def update_project(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Project:
        """
        Update project metadata (name and/or description).
        
        Args:
            tenant_id: Tenant ID for isolation
            team_id: Team ID to verify ownership
            project_id: Project ID to update
            name: Optional new name (1-255 chars)
            description: Optional new description (max 10000 chars)
        
        Returns:
            Updated Project instance
        
        Raises:
            ProjectNotFoundError: If project not found or doesn't belong to team
            ProjectValidationError: If input validation fails
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        """
        # Validate inputs if provided
        name_update = None
        if name is not None:
            if not name.strip():
                raise ProjectValidationError("Project name cannot be empty")
            name_stripped = name.strip()
            if len(name_stripped) > self.MAX_NAME_LENGTH:
                raise ProjectValidationError(
                    f"Project name must be {self.MAX_NAME_LENGTH} characters or less"
                )
            name_update = name_stripped
        
        description_update = None
        if description is not None:
            description_stripped = description.strip() if description else None
            if description_stripped and len(description_stripped) > self.MAX_DESCRIPTION_LENGTH:
                raise ProjectValidationError(
                    f"Project description must be {self.MAX_DESCRIPTION_LENGTH} characters or less"
                )
            description_update = description_stripped
        
        # Build update dict with only provided fields
        update_data = {}
        if name_update is not None:
            update_data["name"] = name_update
        if description_update is not None:
            update_data["description"] = description_update
        
        # If no updates, return existing project
        if not update_data:
            logger.debug(
                "No fields provided for update",
                extra={"tenant_id": tenant_id, "team_id": team_id, "project_id": project_id}
            )
            project = await self.repository.read_by_id_and_team(tenant_id, team_id, project_id)
            if not project:
                raise ProjectNotFoundError("Project not found or access denied")
            return project
        
        try:
            async with self.db.begin():
                updated_project = await self.repository.update(
                    tenant_id, team_id, project_id, **update_data
                )
                if not updated_project:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                logger.info(
                    "Project updated",
                    extra={
                        "tenant_id": tenant_id,
                        "team_id": team_id,
                        "project_id": project_id,
                        "fields": list(update_data.keys())
                    }
                )
                return updated_project
        except (ProjectDataError, RepositoryError) as e:
            logger.error(
                "Failed to update project",
                extra={"tenant_id": tenant_id, "team_id": team_id, "project_id": project_id},
                exc_info=e
            )
            raise
    
    async def update_status(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int,
        new_status: str
    ) -> Project:
        """
        Update project status with state transition validation.
        
        Args:
            tenant_id: Tenant ID for isolation
            team_id: Team ID to verify ownership
            project_id: Project ID to update
            new_status: Target status (active, archived, or inactive)
        
        Returns:
            Updated Project instance
        
        Raises:
            ProjectNotFoundError: If project not found or doesn't belong to team
            InvalidProjectStatusError: If status invalid or transition not allowed
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        """
        # Validate status value
        if new_status not in self.VALID_STATUSES:
            raise InvalidProjectStatusError(
                f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(self.VALID_STATUSES))}"
            )
        
        try:
            async with self.db.begin():
                # Fetch current project to check status
                project = await self.repository.read_by_id_and_team(
                    tenant_id, team_id, project_id
                )
                if not project:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                # Validate transition
                current_status = project.status
                allowed_transitions = self.VALID_TRANSITIONS.get(current_status, [])
                
                if new_status not in allowed_transitions:
                    raise InvalidProjectStatusError(
                        f"Cannot transition from '{current_status}' to '{new_status}'. "
                        f"Allowed: {', '.join(allowed_transitions) or 'none'}"
                    )
                
                # Update status
                updated_project = await self.repository.update(
                    tenant_id, team_id, project_id, status=new_status
                )
                if not updated_project:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                logger.info(
                    "Project status updated",
                    extra={
                        "tenant_id": tenant_id,
                        "team_id": team_id,
                        "project_id": project_id,
                        "old_status": current_status,
                        "new_status": new_status
                    }
                )
                return updated_project
        except (ProjectDataError, RepositoryError) as e:
            logger.error(
                "Failed to update project status",
                extra={"tenant_id": tenant_id, "team_id": team_id, "project_id": project_id},
                exc_info=e
            )
            raise
    
    async def delete_project(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int
    ) -> bool:
        """
        Delete a project.
        
        Args:
            tenant_id: Tenant ID for isolation
            team_id: Team ID to verify ownership
            project_id: Project ID to delete
        
        Returns:
            True if deletion succeeded
        
        Raises:
            ProjectNotFoundError: If project not found or doesn't belong to team
            RepositoryError: If database operation fails
        """
        try:
            async with self.db.begin():
                success = await self.repository.delete(tenant_id, team_id, project_id)
                if not success:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                logger.info(
                    "Project deleted",
                    extra={
                        "tenant_id": tenant_id,
                        "team_id": team_id,
                        "project_id": project_id
                    }
                )
                return True
        except RepositoryError as e:
            logger.error(
                "Failed to delete project",
                extra={"tenant_id": tenant_id, "team_id": team_id, "project_id": project_id},
                exc_info=e
            )
            raise
