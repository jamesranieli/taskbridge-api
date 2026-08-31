from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.project_repository import ProjectRepository
from app.models import Project
from datetime import datetime


class ProjectNotFoundError(Exception):
    """Raised when a project is not found."""
    pass


class InvalidProjectStatusError(Exception):
    """Raised when an invalid project status is provided."""
    pass


class ProjectService:
    """Service layer for Project business logic."""
    
    VALID_STATUSES = ["active", "archived", "inactive"]
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = ProjectRepository(db)
    
    async def create_project(
        self,
        tenant_id: int,
        team_id: int,
        name: str,
        description: str = None
    ) -> Project:
        """
        Create a new project for a team.
        
        Args:
            tenant_id: The tenant ID for tenant isolation
            team_id: The team ID that owns the project
            name: The project name
            description: Optional project description
        
        Returns:
            The created Project model
        
        Raises:
            ValueError: If name is empty or team_id is invalid
        """
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty")
        
        if team_id <= 0:
            raise ValueError("Invalid team_id")
        
        project = await self.repository.create(
            tenant_id=tenant_id,
            team_id=team_id,
            name=name.strip(),
            description=description.strip() if description else None,
            status="active"
        )
        
        # TODO: Log audit event for project creation
        
        return project
    
    async def get_project(self, tenant_id: int, project_id: int) -> Project:
        """
        Get a project by ID.
        
        Args:
            tenant_id: The tenant ID for isolation
            project_id: The project ID to retrieve
        
        Returns:
            The Project model
        
        Raises:
            ProjectNotFoundError: If project doesn't exist
        """
        project = await self.repository.read_by_id(tenant_id, project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found for tenant {tenant_id}")
        
        return project
    
    async def get_project_by_team(self, tenant_id: int, team_id: int, project_id: int) -> Project:
        """
        Get a project by ID with team verification.
        
        Args:
            tenant_id: The tenant ID for isolation
            team_id: The team ID to verify ownership
            project_id: The project ID to retrieve
        
        Returns:
            The Project model
        
        Raises:
            ProjectNotFoundError: If project doesn't exist or doesn't belong to team
        """
        project = await self.repository.read_by_id_and_team(tenant_id, team_id, project_id)
        if not project:
            raise ProjectNotFoundError(
                f"Project {project_id} not found for team {team_id} in tenant {tenant_id}"
            )
        
        return project
    
    async def list_projects_by_team(self, tenant_id: int, team_id: int) -> list[Project]:
        """
        List all projects for a specific team.
        
        Args:
            tenant_id: The tenant ID for isolation
            team_id: The team ID to list projects for
        
        Returns:
            List of Project models
        """
        return await self.repository.list_by_team(tenant_id, team_id)
    
    async def list_all_projects(self, tenant_id: int) -> list[Project]:
        """
        List all projects for a tenant.
        
        Args:
            tenant_id: The tenant ID for isolation
        
        Returns:
            List of Project models
        """
        return await self.repository.list_by_tenant(tenant_id)
    
    async def update_project(
        self,
        tenant_id: int,
        project_id: int,
        name: str = None,
        description: str = None
    ) -> Project:
        """
        Update project details.
        
        Args:
            tenant_id: The tenant ID for isolation
            project_id: The project ID to update
            name: Optional new project name
            description: Optional new description
        
        Returns:
            The updated Project model
        
        Raises:
            ProjectNotFoundError: If project doesn't exist
            ValueError: If name is empty when provided
        """
        project = await self.get_project(tenant_id, project_id)
        
        update_data = {}
        if name is not None:
            if not name.strip():
                raise ValueError("Project name cannot be empty")
            update_data["name"] = name.strip()
        
        if description is not None:
            update_data["description"] = description.strip() if description else None
        
        if not update_data:
            return project
        
        updated_project = await self.repository.update(tenant_id, project_id, **update_data)
        
        # TODO: Log audit event for project update
        
        return updated_project
    
    async def update_status(
        self,
        tenant_id: int,
        project_id: int,
        status: str
    ) -> Project:
        """
        Update project status.
        
        Args:
            tenant_id: The tenant ID for isolation
            project_id: The project ID to update
            status: The new status (active, archived, inactive)
        
        Returns:
            The updated Project model
        
        Raises:
            ProjectNotFoundError: If project doesn't exist
            InvalidProjectStatusError: If status is invalid
        """
        if status not in self.VALID_STATUSES:
            raise InvalidProjectStatusError(
                f"Invalid status '{status}'. Must be one of: {', '.join(self.VALID_STATUSES)}"
            )
        
        project = await self.get_project(tenant_id, project_id)
        
        updated_project = await self.repository.update(tenant_id, project_id, status=status)
        
        # TODO: Log audit event for status change
        
        return updated_project
    
    async def delete_project(self, tenant_id: int, project_id: int) -> bool:
        """
        Soft delete a project.
        
        Args:
            tenant_id: The tenant ID for isolation
            project_id: The project ID to delete
        
        Returns:
            True if deletion was successful
        
        Raises:
            ProjectNotFoundError: If project doesn't exist
        """
        project = await self.get_project(tenant_id, project_id)
        
        success = await self.repository.delete(tenant_id, project_id)
        
        # TODO: Log audit event for project deletion
        
        return success
    
    async def restore_project(self, tenant_id: int, project_id: int) -> Project:
        """
        Restore a soft-deleted project.
        
        Args:
            tenant_id: The tenant ID for isolation
            project_id: The project ID to restore
        
        Returns:
            The restored Project model
        
        Raises:
            ProjectNotFoundError: If project doesn't exist or isn't deleted
        """
        project = await self.repository.restore(tenant_id, project_id)
        if not project:
            raise ProjectNotFoundError(f"Deleted project {project_id} not found for tenant {tenant_id}")
        
        # TODO: Log audit event for project restoration
        
        return project
