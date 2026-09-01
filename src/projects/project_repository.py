"""
Repository layer for Project model with data access and multi-tenant isolation.

This module provides database operations with SQLAlchemy ORM, enforcing
tenant and team isolation on all queries.
"""

from typing import Optional, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from .project import Project

logger = logging.getLogger(__name__)


# Exception hierarchy for repository layer
class RepositoryError(Exception):
    """Base exception for all repository-layer errors."""
    pass


class ProjectDataError(RepositoryError):
    """Raised when database operation fails (integrity, constraint violation)."""
    pass


class ProjectRepository:
    """
    Repository for Project model with enforced tenant and team isolation.
    
    Design:
    - All operations enforce explicit tenant_id filtering
    - Mutation operations (update, delete) require both tenant_id AND team_id
    - This prevents cross-team modifications within a tenant
    - Errors are raised explicitly; None is only returned for "not found" on reads
    """
    
    def __init__(self, db: AsyncSession) -> None:
        """
        Initialize repository with async database session.
        
        Args:
            db (AsyncSession): Database session managed by caller.
        """
        self.db = db
        self.logger = logger
    
    async def create(
        self,
        tenant_id: int,
        team_id: int,
        name: str,
        description: Optional[str] = None,
        status: str = "active"
    ) -> Project:
        """
        Create a new project in the database.
        
        Args:
            tenant_id (int): Tenant ID for multi-tenant isolation
            team_id (int): Team ID (ownership within tenant)
            name (str): Project name (pre-validated by service layer)
            description (Optional[str]): Project description
            status (str): Initial status (default: "active")
        
        Returns:
            Project: Newly created project with auto-assigned ID
        
        Raises:
            ProjectDataError: If database operation fails
        """
        try:
            project = Project(
                tenant_id=tenant_id,
                team_id=team_id,
                name=name,
                description=description,
                status=status
            )
            self.db.add(project)
            await self.db.flush()
            self.logger.info(
                "Created project",
                extra={
                    "project_id": project.id,
                    "tenant_id": tenant_id,
                    "team_id": team_id,
                    "name": name
                }
            )
            return project
        except IntegrityError as e:
            self.logger.error(
                "Integrity error creating project",
                extra={"tenant_id": tenant_id, "team_id": team_id, "name": name},
                exc_info=e
            )
            raise ProjectDataError(f"Failed to create project: {str(e)}") from e
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error creating project",
                extra={"tenant_id": tenant_id},
                exc_info=e
            )
            raise ProjectDataError(f"Database error: {str(e)}") from e
    
    async def read_by_id(
        self,
        tenant_id: int,
        project_id: int
    ) -> Optional[Project]:
        """
        Read a project by ID with tenant isolation (no team verification).
        
        Args:
            tenant_id (int): Tenant ID for isolation
            project_id (int): Project ID to retrieve
        
        Returns:
            Optional[Project]: Project if found; None otherwise
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            result = await self.db.execute(
                select(Project).where(
                    and_(
                        Project.id == project_id,
                        Project.tenant_id == tenant_id
                    )
                )
            )
            project = result.scalar_one_or_none()
            if project:
                self.logger.debug(
                    "Retrieved project by ID",
                    extra={"project_id": project_id, "tenant_id": tenant_id}
                )
            return project
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error reading project",
                extra={"project_id": project_id, "tenant_id": tenant_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def read_by_id_and_team(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int
    ) -> Optional[Project]:
        """
        Read a project by ID with both tenant AND team isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to verify ownership
            project_id (int): Project ID to retrieve
        
        Returns:
            Optional[Project]: Project if found and owned by team; None otherwise
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            result = await self.db.execute(
                select(Project).where(
                    and_(
                        Project.id == project_id,
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id
                    )
                )
            )
            project = result.scalar_one_or_none()
            if project:
                self.logger.debug(
                    "Retrieved project by ID and team",
                    extra={
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                        "team_id": team_id
                    }
                )
            return project
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error reading project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                },
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def list_by_tenant(
        self,
        tenant_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[Project]:
        """
        List projects for a tenant with pagination.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            limit (int): Max results per page
            offset (int): Number of results to skip
        
        Returns:
            List[Project]: List of projects (empty list if none found)
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            result = await self.db.execute(
                select(Project)
                .where(Project.tenant_id == tenant_id)
                .order_by(Project.id)
                .limit(limit)
                .offset(offset)
            )
            projects = result.scalars().all()
            self.logger.debug(
                "Listed projects by tenant",
                extra={
                    "tenant_id": tenant_id,
                    "limit": limit,
                    "offset": offset,
                    "count": len(projects)
                }
            )
            return projects
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error listing projects",
                extra={"tenant_id": tenant_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def list_by_team(
        self,
        tenant_id: int,
        team_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[Project]:
        """
        List projects for a team with pagination.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to list projects for
            limit (int): Max results per page
            offset (int): Number of results to skip
        
        Returns:
            List[Project]: List of projects (empty list if none found)
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            result = await self.db.execute(
                select(Project)
                .where(
                    and_(
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id
                    )
                )
                .order_by(Project.id)
                .limit(limit)
                .offset(offset)
            )
            projects = result.scalars().all()
            self.logger.debug(
                "Listed projects by team",
                extra={
                    "tenant_id": tenant_id,
                    "team_id": team_id,
                    "limit": limit,
                    "offset": offset,
                    "count": len(projects)
                }
            )
            return projects
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error listing projects",
                extra={"tenant_id": tenant_id, "team_id": team_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def count_by_tenant(self, tenant_id: int) -> int:
        """
        Count total projects for a tenant.
        
        Args:
            tenant_id (int): Tenant ID for isolation
        
        Returns:
            int: Total count of projects
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            result = await self.db.execute(
                select(func.count(Project.id)).where(
                    Project.tenant_id == tenant_id
                )
            )
            count = result.scalar_one()
            return count or 0
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error counting projects",
                extra={"tenant_id": tenant_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def count_by_team(self, tenant_id: int, team_id: int) -> int:
        """
        Count total projects for a team.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID for filtering
        
        Returns:
            int: Total count of projects in the team
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            result = await self.db.execute(
                select(func.count(Project.id)).where(
                    and_(
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id
                    )
                )
            )
            count = result.scalar_one()
            return count or 0
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error counting projects",
                extra={"tenant_id": tenant_id, "team_id": team_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def update(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int,
        **kwargs
    ) -> Optional[Project]:
        """
        Update a project's attributes with tenant and team isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to verify project ownership
            project_id (int): Project ID to update
            **kwargs: Field updates (name, description, status, etc.)
        
        Returns:
            Optional[Project]: Updated project; None if not found or not owned by team
        
        Raises:
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        """
        try:
            # Fetch project with team isolation to prevent cross-team mutations
            project = await self.read_by_id_and_team(tenant_id, team_id, project_id)
            if not project:
                self.logger.warning(
                    "Project not found for update (team isolation enforced)",
                    extra={
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                        "team_id": team_id
                    }
                )
                return None
            
            # Apply updates to provided fields
            for key, value in kwargs.items():
                if hasattr(project, key):
                    setattr(project, key, value)
            
            await self.db.flush()
            self.logger.info(
                "Updated project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id,
                    "fields_updated": list(kwargs.keys())
                }
            )
            return project
        except IntegrityError as e:
            self.logger.error(
                "Integrity error updating project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                },
                exc_info=e
            )
            raise ProjectDataError(f"Failed to update project: {str(e)}") from e
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error updating project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                },
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def delete(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int
    ) -> bool:
        """
        Delete a project with tenant and team isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to verify project ownership
            project_id (int): Project ID to delete
        
        Returns:
            bool: True if deletion succeeded; False if project not found or not owned by team
        
        Raises:
            RepositoryError: If database operation fails
        """
        try:
            # Fetch project with team isolation to prevent cross-team deletions
            project = await self.read_by_id_and_team(tenant_id, team_id, project_id)
            if not project:
                self.logger.warning(
                    "Project not found for deletion (team isolation enforced)",
                    extra={
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                        "team_id": team_id
                    }
                )
                return False
            
            await self.db.delete(project)
            await self.db.flush()
            self.logger.info(
                "Deleted project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                }
            )
            return True
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error deleting project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                },
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
