"""
Repository layer for Project model with data access and multi-tenant isolation.

This module provides database operations with explicit error handling, logging,
and transaction safety. Multi-tenant boundaries are enforced on all queries.

Lifecycle and Transaction Management:
- AsyncSession is managed by caller (typically FastAPI dependency injection)
- Repository methods use flush() to persist changes without committing
- Caller is responsible for transaction boundaries and session lifecycle
- Explicit errors are raised; no silent failures or None returns for errors
- Only "not found" conditions return None for read operations

Multi-Tenant Isolation:
- All read operations require tenant_id
- Mutation operations (update, delete, restore) require tenant_id + team_id
- This prevents cross-team mutations within a tenant
"""

from typing import Optional, List, Any
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


class ProjectNotFoundError(RepositoryError):
    """Raised when a project cannot be found in the database."""
    pass


class ProjectDataError(RepositoryError):
    """Raised when database operation fails (integrity, constraint violation)."""
    pass


class ProjectRepository:
    """
    Repository for Project model with enforced tenant and team isolation.
    
    Design:
    - All operations enforce explicit tenant_id filtering
    - Mutation operations (update, delete, restore) require both tenant_id AND team_id
    - This prevents inadvertent cross-team modifications within a tenant
    - Soft-deleted projects are excluded from queries by default (is_deleted=False)
    - Errors are raised explicitly; None is only returned for "not found" on reads
    - Structured logging included for debugging and monitoring
    """
    
    def __init__(self, db: AsyncSession) -> None:
        """
        Initialize repository with async database session.
        
        Args:
            db (AsyncSession): Database session managed by caller.
                               Typically injected via FastAPI dependency.
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
            ProjectDataError: If database operation fails (constraint violation, etc.)
        
        Note:
            - Does NOT validate team_id existence (service layer responsibility)
            - Timestamps are auto-set by ORM
            - Caller must commit transaction to persist
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
            await self.db.flush()  # Persist to DB and assign ID, but don't commit
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
            Optional[Project]: Project if found and not deleted; None otherwise
        
        Raises:
            RepositoryError: If database query fails
        
        Note:
            - Returns non-deleted projects only (is_deleted=False)
            - Does NOT verify team ownership
            - Use read_by_id_and_team() for team isolation
            - Suitable for admin/cross-team queries within a tenant
        """
        try:
            result = await self.db.execute(
                select(Project).where(
                    and_(
                        Project.id == project_id,
                        Project.tenant_id == tenant_id,
                        Project.is_deleted == False
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
            Optional[Project]: Project if found, owned by team, and not deleted; None otherwise
        
        Raises:
            RepositoryError: If database query fails
        
        Note:
            - Returns non-deleted projects only
            - Enforces team ownership as authorization boundary
            - Use this for user-facing operations requiring team context
            - Critical for preventing cross-team access
        """
        try:
            result = await self.db.execute(
                select(Project).where(
                    and_(
                        Project.id == project_id,
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id,
                        Project.is_deleted == False
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
        List non-deleted projects for a tenant with pagination.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            limit (int): Max results per page (1-1000, default 100)
            offset (int): Number of results to skip
        
        Returns:
            List[Project]: List of projects (empty list if none found)
        
        Raises:
            ValueError: If limit or offset are invalid
            RepositoryError: If database query fails
        
        Note:
            - Results ordered by created_at descending (newest first)
            - Only non-deleted projects
            - Pagination handled at repository level
        """
        if not (1 <= limit <= 1000):
            raise ValueError("Limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        
        try:
            result = await self.db.execute(
                select(Project)
                .where(
                    and_(
                        Project.tenant_id == tenant_id,
                        Project.is_deleted == False
                    )
                )
                .order_by(Project.created_at.desc())
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
        List non-deleted projects for a team with pagination.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to list projects for
            limit (int): Max results per page (1-1000, default 100)
            offset (int): Number of results to skip
        
        Returns:
            List[Project]: List of projects (empty list if none found)
        
        Raises:
            ValueError: If limit or offset are invalid
            RepositoryError: If database query fails
        
        Note:
            - Results ordered by created_at descending (newest first)
            - Enforces both tenant and team isolation
            - Only non-deleted projects
        """
        if not (1 <= limit <= 1000):
            raise ValueError("Limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        
        try:
            result = await self.db.execute(
                select(Project)
                .where(
                    and_(
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id,
                        Project.is_deleted == False
                    )
                )
                .order_by(Project.created_at.desc())
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
        Count total non-deleted projects for a tenant.
        
        Args:
            tenant_id (int): Tenant ID for isolation
        
        Returns:
            int: Total count of non-deleted projects
        
        Raises:
            RepositoryError: If database query fails
        
        Note:
            - Used for pagination metadata
            - Only counts non-deleted projects
        """
        try:
            result = await self.db.execute(
                select(func.count(Project.id)).where(
                    and_(
                        Project.tenant_id == tenant_id,
                        Project.is_deleted == False
                    )
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
        Count total non-deleted projects for a team.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID for filtering
        
        Returns:
            int: Total count of non-deleted projects in the team
        
        Raises:
            RepositoryError: If database query fails
        
        Note:
            - Used for pagination metadata
            - Only counts non-deleted projects
        """
        try:
            result = await self.db.execute(
                select(func.count(Project.id)).where(
                    and_(
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id,
                        Project.is_deleted == False
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
        **kwargs: Any
    ) -> Optional[Project]:
        """
        Update a project's attributes with tenant and team isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to verify project ownership (REQUIRED for mutations)
            project_id (int): Project ID to update
            **kwargs: Field updates (name, description, status, etc.)
        
        Returns:
            Optional[Project]: Updated project; None if project not found or not owned by team
        
        Raises:
            ValueError: If attempting to update immutable fields
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        
        Note:
            - Enforces BOTH tenant_id AND team_id (prevents cross-team mutations)
            - updated_at is auto-managed by ORM (onupdate trigger)
            - Immutable fields: id, tenant_id, team_id, created_at, is_deleted
            - Caller must commit transaction to persist
            - Only updates non-deleted projects
        """
        # Validate immutable fields to prevent accidental modification
        immutable_fields = {"id", "tenant_id", "team_id", "created_at", "is_deleted"}
        for key in kwargs.keys():
            if key in immutable_fields:
                raise ValueError(f"Cannot update immutable field: {key}")
        
        try:
            # Fetch project with TEAM isolation to prevent cross-team mutations
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
            
            # Apply updates only to provided fields
            for key, value in kwargs.items():
                if hasattr(project, key):
                    setattr(project, key, value)
            
            # Flush to persist changes without committing
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
        Soft delete a project with tenant and team isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to verify project ownership (REQUIRED for mutations)
            project_id (int): Project ID to delete
        
        Returns:
            bool: True if deletion succeeded; False if project not found or not owned by team
        
        Raises:
            RepositoryError: If database operation fails
        
        Note:
            - Enforces BOTH tenant_id AND team_id (prevents cross-team deletions)
            - Soft delete preserves data and audit history
            - updated_at is auto-managed by ORM (onupdate trigger)
            - Project remains in database for compliance/audit purposes
            - Caller must commit transaction to persist
        """
        try:
            # Fetch project with TEAM isolation to prevent cross-team mutations
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
            
            # Soft delete by setting is_deleted flag
            project.is_deleted = True
            await self.db.flush()
            self.logger.info(
                "Soft deleted project",
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
    
    async def restore(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int
    ) -> Optional[Project]:
        """
        Restore a soft-deleted project with tenant and team isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            team_id (int): Team ID to verify project ownership (REQUIRED for mutations)
            project_id (int): Project ID to restore
        
        Returns:
            Optional[Project]: Restored project; None if deleted project not found or not owned by team
        
        Raises:
            RepositoryError: If database operation fails
        
        Note:
            - Enforces BOTH tenant_id AND team_id (prevents cross-team restores)
            - Only works on projects with is_deleted=True
            - updated_at is auto-managed by ORM (onupdate trigger)
            - Caller must commit transaction to persist
        """
        try:
            result = await self.db.execute(
                select(Project).where(
                    and_(
                        Project.id == project_id,
                        Project.tenant_id == tenant_id,
                        Project.team_id == team_id,
                        Project.is_deleted == True
                    )
                )
            )
            project = result.scalar_one_or_none()
            if not project:
                self.logger.warning(
                    "Deleted project not found for restoration (team isolation enforced)",
                    extra={
                        "project_id": project_id,
                        "tenant_id": tenant_id,
                        "team_id": team_id
                    }
                )
                return None
            
            # Restore by clearing is_deleted flag
            project.is_deleted = False
            await self.db.flush()
            self.logger.info(
                "Restored project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                }
            )
            return project
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error restoring project",
                extra={
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "team_id": team_id
                },
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
