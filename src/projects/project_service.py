"""
Service layer for Project business logic and orchestration.

This module provides the service layer for all project-related operations,
enforcing business rules, input validation, tenant/team isolation, status
transitions, and error handling.

Design Principles:
- Dependency injection: repository and db session injected via constructor
- Tenant & team isolation: ALL mutations require both tenant_id and team_id
- Transaction boundaries: explicit transaction contexts (db.begin()) for mutations
- Error handling: explicit exceptions with clear messages, no silent failures
- Validation: input, status transitions, and business rules enforced here
- Logging: structured logging for debugging and audit trail
- Team-to-tenant validation: NOT performed by service (Team model/repo not available).
  Relies on tenant_id + team_id filtering to prevent cross-team mutations within tenant.
  NOTE: This does not guarantee team_id belongs to tenant_id—database FK alone cannot
  enforce this without a Team model. See "Limitations" section.
- Project create, status update, and delete integrate immutable audit logging and notification fan-out within the same transaction

Transaction Handling:
- Service establishes explicit transaction boundaries for mutation operations
- Uses AsyncSession.begin() context manager which auto-commits on success and auto-rollbacks on exception
- Mutations are atomic within the transaction; no partial updates on failure
- Read operations inside mutation transactions are part of the same transaction
- No nested transactions are used; each mutation operation is one top-level transaction
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .project import Project
from .project_repository import (
    ProjectRepository,
    ProjectDataError,
    RepositoryError
)
from src.notifications.services import (
    AuditService,
    NotificationService,
    AuditCreateServiceError,
    NotificationCreateServiceError,
    ValidationServiceError as NotificationAuditValidationServiceError,
)

logger = logging.getLogger(__name__)


# Service-layer exception hierarchy
class ServiceError(Exception):
    """Base exception for all service-layer errors."""
    pass


class ProjectNotFoundError(ServiceError):
    """Raised when a project cannot be found or accessed."""
    pass


class InvalidProjectStatusError(ServiceError):
    """Raised when a project status transition is invalid."""
    pass


class ProjectService:
    """
    Service layer for Project business logic and orchestration.
    
    Manages project creation, updates, deletions, and status transitions.
    Enforces multi-tenant isolation, team-based authorization, input validation,
    status state machine, and business rules.
    
    Design:
    - All mutations require both tenant_id AND team_id for team-level authorization
    - read_by_id() (tenant-only) available for cross-team admin queries
    - read_by_id_and_team() enforces team boundary for user operations
    - Status transitions validated against state machine rules
    - Input validation includes length limits and format checks
    - Structured logging for monitoring and debugging
    - Explicit transaction boundaries established via db.begin() context manager
    
    LIMITATIONS (pending Team & Tenant model integration):
    - team_id is used to filter projects but NOT validated to exist or belong to tenant
    - Database FK constraint on teams.id prevents orphaned team_ids at DB level only
    - This provides isolation (cross-team access prevented) but not full validation
    - Future: when Team model/repository available, add team existence and ownership checks
    - Until then, assume team_id is pre-validated by caller or API layer
    
    Args:
        db: AsyncSession instance for database operations.
            Typically injected via FastAPI dependency.
    
    Example:
        >>> service = ProjectService(db)
        >>> project = await service.create_project(
        ...     tenant_id=1,
        ...     team_id=5,
        ...     name="Mobile App",
        ...     description="iOS and Android"
        ... )
    """
    
    # Valid project statuses
    VALID_STATUSES = frozenset(["active", "archived", "inactive"])
    
    # Valid state transitions: source_status -> [allowed_target_statuses]
    VALID_TRANSITIONS = {
        "active": ["archived", "inactive"],
        "archived": ["active"],
        "inactive": ["active"]
    }
    
    # Input validation constraints
    MAX_PROJECT_NAME_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 10000
    
    def __init__(self, db: AsyncSession) -> None:
        """
        Initialize service with database session.
        
        Args:
            db: AsyncSession instance managed by caller (e.g., FastAPI dependency).
        
        Transaction Boundary Ownership:
        - Service creates explicit transaction contexts for mutations (create, update, delete, restore)
        - AsyncSession.begin() context manager automatically commits on success, rolls back on exception
        - Service handles all transaction management; caller does not need to commit after service calls
        - Read operations use existing session without explicit transaction
        """
        self.db = db
        self.repository = ProjectRepository(db)
        self.logger = logger
    
    # ==================== CREATE OPERATIONS ====================
    
    async def create_project(
        self,
        tenant_id: int,
        team_id: int,
        name: str,
        description: Optional[str] = None,
        *,
        actor_user_id: int,
        actor_organisation_id: int,
        recipient_user_ids: list[int],
    ) -> Project:
        """
        Create a new project for a team.
        
        Validates input (name, description), creates project with "active" status.
        Establishes explicit transaction boundary for atomicity.
        
        Args:
            tenant_id: Tenant ID for multi-tenant isolation (required)
            team_id: Team ID that owns the project (required)
                     NOTE: Not validated for existence or ownership; caller must pre-validate
            name: Project name (1-255 chars, required, stripped of whitespace)
            description: Optional project description (max 10000 chars)
        
        Returns:
            Created Project instance with auto-assigned ID
        
        Raises:
            ValueError: If name is empty, too long, or description exceeds max length
            ProjectDataError: If database operation fails (constraint violation, etc.)
            RepositoryError: If database query fails
        
        Transaction Guarantee:
        - Mutation is wrapped in AsyncSession.begin() context
        - On success: transaction is automatically committed
        - On failure: transaction is automatically rolled back
        - Operation is atomic; no partial state on failure
        
        Note:
            - Status is always "active" on creation (immutable)
            - Audit logging and notification fan-out are performed atomically within the same transaction
        """
        # Input validation: name
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty")
        
        name_stripped = name.strip()
        if len(name_stripped) > self.MAX_PROJECT_NAME_LENGTH:
            raise ValueError(
                f"Project name must be {self.MAX_PROJECT_NAME_LENGTH} characters or less"
            )
        
        # Input validation: description
        description_stripped = None
        if description:
            description_stripped = description.strip()
            if description_stripped and len(description_stripped) > self.MAX_DESCRIPTION_LENGTH:
                raise ValueError(
                    f"Project description must be {self.MAX_DESCRIPTION_LENGTH} characters or less"
                )
        
        # Input validation: team_id
        if team_id <= 0:
            raise ValueError("Invalid team_id: must be positive integer")

        # Integration context validation
        self._validate_integration_context(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_organisation_id=actor_organisation_id,
            recipient_user_ids=recipient_user_ids,
        )
        
        try:
            # Establish transaction boundary for create operation
            async with self.db.begin():
                project = await self.repository.create(
                    tenant_id=tenant_id,
                    team_id=team_id,
                    name=name_stripped,
                    description=description_stripped,
                    status="active"
                )
                
                self.logger.info(
                    "Project created",
                    extra={
                        "project_id": project.id,
                        "team_id": team_id,
                        "name": name_stripped
                    }
                )

                # Audit + notifications in same transaction
                audit_service = AuditService(self.db)
                notification_service = NotificationService(self.db)
                created_snapshot = self._serialize_project_snapshot(project)

                await audit_service.create_audit_entry(
                    tenant_id=tenant_id,
                    event_type="project_created",
                    entity_type="project",
                    entity_id=project.id,
                    actor_user_id=actor_user_id,
                    actor_organisation_id=actor_organisation_id,
                    previous_state=None,
                    new_state=created_snapshot,
                )

                await notification_service.create_notifications_for_recipients(
                    tenant_id=tenant_id,
                    recipient_user_ids=recipient_user_ids,
                    event_type="project_created",
                    project_id=project.id,
                    message=f"Project '{project.name}' was created.",
                )
                
                return project
        
        except (
            ProjectDataError,
            RepositoryError,
            AuditCreateServiceError,
            NotificationCreateServiceError,
            NotificationAuditValidationServiceError,
        ) as e:
            self.logger.error(
                "Failed to create project",
                extra={"team_id": team_id, "name": name_stripped},
                exc_info=e
            )
            raise
    
    # ==================== READ OPERATIONS ====================
    
    async def get_project(self, tenant_id: int, project_id: int) -> Project:
        """
        Get a project by ID with tenant isolation (no team verification).
        
        Use this for admin/cross-team queries where team context is not available.
        For user-facing operations, use get_project_by_team() instead.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            project_id: Project ID to retrieve (required)
        
        Returns:
            Project instance
        
        Raises:
            ProjectNotFoundError: If project not found, belongs to different tenant, or is deleted
            RepositoryError: If database query fails
        
        Note:
            - Read operation; no explicit transaction boundary
            - Does NOT verify team ownership
        """
        try:
            project = await self.repository.read_by_id(tenant_id, project_id)
            if not project:
                raise ProjectNotFoundError("Project not found")
            
            self.logger.debug(
                "Retrieved project by ID",
                extra={"project_id": project_id}
            )
            return project
        
        except RepositoryError as e:
            self.logger.error(
                "Failed to retrieve project",
                extra={"project_id": project_id},
                exc_info=e
            )
            raise
    
    async def get_project_by_team(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int
    ) -> Project:
        """
        Get a project by ID with team-level authorization verification.
        
        Ensures project belongs to specified team and tenant. Use for all
        user-facing operations requiring team context.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            team_id: Team ID to verify project ownership (required)
            project_id: Project ID to retrieve (required)
        
        Returns:
            Project instance
        
        Raises:
            ProjectNotFoundError: If project not found, doesn't belong to team,
                                  belongs to different tenant, or is deleted
            RepositoryError: If database query fails
        
        Note:
            - Read operation; no explicit transaction boundary
            - Returns same generic error message for all not-found cases to avoid
              leaking information about project existence across teams
        """
        try:
            project = await self.repository.read_by_id_and_team(
                tenant_id, team_id, project_id
            )
            if not project:
                raise ProjectNotFoundError("Project not found or access denied")
            
            self.logger.debug(
                "Retrieved project by team",
                extra={"project_id": project_id, "team_id": team_id}
            )
            return project
        
        except RepositoryError as e:
            self.logger.error(
                "Failed to retrieve project",
                extra={"project_id": project_id, "team_id": team_id},
                exc_info=e
            )
            raise
    
    async def list_projects_by_team(
        self,
        tenant_id: int,
        team_id: int,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[list[Project], int]:
        """
        List all projects for a team with pagination.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            team_id: Team ID to list projects for (required)
            limit: Max results per page (1-1000, default 20)
            offset: Number of results to skip (default 0)
        
        Returns:
            Tuple of (projects list, total count) for pagination
        
        Raises:
            ValueError: If limit or offset are invalid
            RepositoryError: If database query fails
        
        Note:
            - Read operation; no explicit transaction boundary
            - Results ordered by created_at descending (newest first)
            - Only non-deleted projects returned
            - Total count excludes limit/offset (useful for pagination UI)
        """
        # Validate pagination parameters
        if not (1 <= limit <= 1000):
            raise ValueError("Limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        
        try:
            projects = await self.repository.list_by_team(
                tenant_id, team_id, limit=limit, offset=offset
            )
            total_count = await self.repository.count_by_team(tenant_id, team_id)
            
            self.logger.debug(
                "Listed projects by team",
                extra={
                    "team_id": team_id,
                    "limit": limit,
                    "offset": offset,
                    "count": len(projects),
                    "total": total_count
                }
            )
            return projects, total_count
        
        except RepositoryError as e:
            self.logger.error(
                "Failed to list projects",
                extra={"team_id": team_id},
                exc_info=e
            )
            raise
    
    async def list_all_projects(
        self,
        tenant_id: int,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[list[Project], int]:
        """
        List all projects for a tenant with pagination (cross-team).
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            limit: Max results per page (1-1000, default 20)
            offset: Number of results to skip (default 0)
        
        Returns:
            Tuple of (projects list, total count) for pagination
        
        Raises:
            ValueError: If limit or offset are invalid
            RepositoryError: If database query fails
        
        Note:
            - Read operation; no explicit transaction boundary
            - No team filtering (returns all tenant projects)
            - Results ordered by created_at descending
            - Only non-deleted projects returned
        """
        # Validate pagination parameters
        if not (1 <= limit <= 1000):
            raise ValueError("Limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        
        try:
            projects = await self.repository.list_by_tenant(
                tenant_id, limit=limit, offset=offset
            )
            total_count = await self.repository.count_by_tenant(tenant_id)
            
            self.logger.debug(
                "Listed all projects by tenant",
                extra={
                    "limit": limit,
                    "offset": offset,
                    "count": len(projects),
                    "total": total_count
                }
            )
            return projects, total_count
        
        except RepositoryError as e:
            self.logger.error(
                "Failed to list projects",
                exc_info=e
            )
            raise
    
    # ==================== UPDATE OPERATIONS ====================
    
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
        
        For status updates, use update_status() instead to enforce state transitions.
        Requires team-level authorization (team_id parameter).
        Establishes explicit transaction boundary for atomicity.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            team_id: Team ID to verify project ownership (required)
            project_id: Project ID to update (required)
            name: Optional new project name (1-255 chars, stripped)
            description: Optional new description (max 10000 chars)
        
        Returns:
            Updated Project instance
        
        Raises:
            ProjectNotFoundError: If project not found, doesn't belong to team,
                                  or belongs to different tenant
            ValueError: If name is empty/too long or description too long
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        
        Transaction Guarantee:
        - Mutation is wrapped in AsyncSession.begin() context
        - On success: transaction is automatically committed
        - On failure: transaction is automatically rolled back
        - Operation is atomic; no partial state on failure
        
        Note:
            - At least one field must be provided (name or description)
            - If no fields provided, returns existing project unchanged
            - Returns generic error if project not found (avoids leaking team info)
        """
        # Validate input: name (if provided)
        name_update = None
        if name is not None:
            if not name.strip():
                raise ValueError("Project name cannot be empty")
            name_stripped = name.strip()
            if len(name_stripped) > self.MAX_PROJECT_NAME_LENGTH:
                raise ValueError(
                    f"Project name must be {self.MAX_PROJECT_NAME_LENGTH} characters or less"
                )
            name_update = name_stripped
        
        # Validate input: description (if provided)
        description_update = None
        if description is not None:
            description_stripped = description.strip() if description else None
            if description_stripped and len(description_stripped) > self.MAX_DESCRIPTION_LENGTH:
                raise ValueError(
                    f"Project description must be {self.MAX_DESCRIPTION_LENGTH} characters or less"
                )
            description_update = description_stripped
        
        # Build update data (only provided fields)
        update_data = {}
        if name_update is not None:
            update_data["name"] = name_update
        if description_update is not None:
            update_data["description"] = description_update
        
        # If no updates provided, return existing project
        if not update_data:
            self.logger.debug(
                "No fields provided for update",
                extra={"project_id": project_id, "team_id": team_id}
            )
            return await self.get_project_by_team(tenant_id, team_id, project_id)
        
        try:
            # Establish transaction boundary for update operation
            async with self.db.begin():
                updated_project = await self.repository.update(
                    tenant_id, team_id, project_id, **update_data
                )
                
                if not updated_project:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                self.logger.info(
                    "Project updated",
                    extra={
                        "project_id": project_id,
                        "team_id": team_id,
                        "fields": list(update_data.keys())
                    }
                )
                
                # TODO: Call audit_service.log_update() with field changes
                
                return updated_project
        
        except (ProjectDataError, RepositoryError) as e:
            self.logger.error(
                "Failed to update project",
                extra={"project_id": project_id, "team_id": team_id},
                exc_info=e
            )
            raise
    
    async def update_status(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int,
        new_status: str,
        actor_user_id: int,
        actor_organisation_id: int,
        recipient_user_ids: list[int],
    ) -> Project:
        """
        Update project status with state-transition validation.
        
        Validates that the requested status transition is allowed by the
        state machine (VALID_TRANSITIONS). Requires team-level authorization.
        Establishes explicit transaction boundary for atomicity.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            team_id: Team ID to verify project ownership (required)
            project_id: Project ID to update (required)
            new_status: Target status (must be valid transition from current status)
        
        Returns:
            Updated Project instance
        
        Raises:
            ProjectNotFoundError: If project not found, doesn't belong to team,
                                  or belongs to different tenant
            InvalidProjectStatusError: If new_status is not in VALID_STATUSES or
                                       if transition is not allowed
            ProjectDataError: If database operation fails
            RepositoryError: If database query fails
        
        Transaction Guarantee:
        - Mutation is wrapped in AsyncSession.begin() context
        - On success: transaction is automatically committed
        - On failure: transaction is automatically rolled back
        - Operation is atomic; no partial state on failure
        - Read (current status check) and write (update) occur in same transaction
        
        Note:
            - Valid statuses: active, archived, inactive
            - Valid transitions:
              * active -> archived, inactive
              * archived -> active
              * inactive -> active
            - Returns generic error if project not found (avoids leaking team info)
        """
        # Validate status value
        if new_status not in self.VALID_STATUSES:
            raise InvalidProjectStatusError(
                f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(self.VALID_STATUSES))}"
            )

        # Integration context validation
        self._validate_integration_context(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_organisation_id=actor_organisation_id,
            recipient_user_ids=recipient_user_ids,
        )
        
        try:
            # Establish transaction boundary for update operation
            # Both read (fetch current state) and write (update status) occur in same transaction
            async with self.db.begin():
                # Fetch project to check current status
                project = await self.repository.read_by_id_and_team(
                    tenant_id, team_id, project_id
                )
                if not project:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                # Validate status transition
                current_status = project.status
                before_snapshot = self._serialize_project_snapshot(project)
                allowed_transitions = self.VALID_TRANSITIONS.get(current_status, [])
                
                if new_status not in allowed_transitions:
                    raise InvalidProjectStatusError(
                        f"Cannot transition from '{current_status}' to '{new_status}'. "
                        f"Allowed transitions from '{current_status}': {', '.join(allowed_transitions) or 'none'}"
                    )
                
                # Perform atomic update with team isolation
                updated_project = await self.repository.update(
                    tenant_id, team_id, project_id, status=new_status
                )
                
                if not updated_project:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                self.logger.info(
                    "Project status updated",
                    extra={
                        "project_id": project_id,
                        "team_id": team_id,
                        "old_status": current_status,
                        "new_status": new_status
                    }
                )

                # Audit + notifications in same transaction
                audit_service = AuditService(self.db)
                notification_service = NotificationService(self.db)
                after_snapshot = self._serialize_project_snapshot(updated_project)

                await audit_service.create_audit_entry(
                    tenant_id=tenant_id,
                    event_type="project_status_updated",
                    entity_type="project",
                    entity_id=project_id,
                    actor_user_id=actor_user_id,
                    actor_organisation_id=actor_organisation_id,
                    previous_state=before_snapshot,
                    new_state=after_snapshot,
                )

                await notification_service.create_notifications_for_recipients(
                    tenant_id=tenant_id,
                    recipient_user_ids=recipient_user_ids,
                    event_type="project_status_updated",
                    project_id=updated_project.id,
                    message=(
                        f"Project '{updated_project.name}' status changed from "
                        f"'{current_status}' to '{new_status}'."
                    ),
                )
                
                return updated_project
        
        except (
            ProjectDataError,
            RepositoryError,
            AuditCreateServiceError,
            NotificationCreateServiceError,
            NotificationAuditValidationServiceError,
        ) as e:
            self.logger.error(
                "Failed to update project status",
                extra={"project_id": project_id, "team_id": team_id},
                exc_info=e
            )
            raise
    
    # ==================== DELETE OPERATIONS ====================
    
    async def delete_project(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int,
        actor_user_id: int,
        actor_organisation_id: int,
        recipient_user_ids: list[int],
    ) -> bool:
        """
        Soft delete a project.
        
        Marks project as deleted (is_deleted=True) without removing from database.
        Preserves data and audit history. Requires team-level authorization.
        Establishes explicit transaction boundary for atomicity.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            team_id: Team ID to verify project ownership (required)
            project_id: Project ID to delete (required)
        
        Returns:
            True if deletion succeeded
        
        Raises:
            ProjectNotFoundError: If project not found, doesn't belong to team,
                                  or belongs to different tenant
            RepositoryError: If database operation fails
        
        Transaction Guarantee:
        - Mutation is wrapped in AsyncSession.begin() context
        - On success: transaction is automatically committed
        - On failure: transaction is automatically rolled back
        - Operation is atomic; no partial state on failure
        - Read (verify project exists) and write (delete) occur in same transaction
        
        Note:
            - Soft delete preserves data for compliance and audit purposes
            - Deleted project is hidden from list operations
            - Deleted project can be restored with restore_project()
            - Returns generic error if project not found (avoids leaking team info)
        """
        self._validate_integration_context(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_organisation_id=actor_organisation_id,
            recipient_user_ids=recipient_user_ids,
        )

        try:
            # Establish transaction boundary for delete operation
            # Both read (verify project exists) and write (soft delete) occur in same transaction
            async with self.db.begin():
                # Verify project exists and belongs to team
                project = await self.repository.read_by_id_and_team(
                    tenant_id, team_id, project_id
                )
                if not project:
                    raise ProjectNotFoundError("Project not found or access denied")
                before_snapshot = self._serialize_project_snapshot(project)
                
                # Perform atomic soft delete with team isolation
                success = await self.repository.delete(tenant_id, team_id, project_id)
                
                if not success:
                    raise ProjectNotFoundError("Project not found or access denied")
                
                self.logger.info(
                    "Project deleted",
                    extra={
                        "project_id": project_id,
                        "team_id": team_id
                    }
                )

                # Audit + notifications in same transaction
                audit_service = AuditService(self.db)
                notification_service = NotificationService(self.db)

                await audit_service.create_audit_entry(
                    tenant_id=tenant_id,
                    event_type="project_deleted",
                    entity_type="project",
                    entity_id=project_id,
                    actor_user_id=actor_user_id,
                    actor_organisation_id=actor_organisation_id,
                    previous_state=before_snapshot,
                    new_state=None,
                )

                await notification_service.create_notifications_for_recipients(
                    tenant_id=tenant_id,
                    recipient_user_ids=recipient_user_ids,
                    event_type="project_deleted",
                    project_id=project.id,
                    message=f"Project '{project.name}' was deleted.",
                )
                
                return True
        
        except (
            RepositoryError,
            AuditCreateServiceError,
            NotificationCreateServiceError,
            NotificationAuditValidationServiceError,
        ) as e:
            self.logger.error(
                "Failed to delete project",
                extra={"project_id": project_id, "team_id": team_id},
                exc_info=e
            )
            raise
    
    async def restore_project(
        self,
        tenant_id: int,
        team_id: int,
        project_id: int
    ) -> Project:
        """
        Restore a soft-deleted project.
        
        Clears is_deleted flag to make project visible again.
        Requires team-level authorization.
        Establishes explicit transaction boundary for atomicity.
        
        Args:
            tenant_id: Tenant ID for isolation (required)
            team_id: Team ID to verify project ownership (required)
            project_id: Project ID to restore (required)
        
        Returns:
            Restored Project instance
        
        Raises:
            ProjectNotFoundError: If project not found, not deleted,
                                  doesn't belong to team, or belongs to different tenant
            RepositoryError: If database operation fails
        
        Transaction Guarantee:
        - Mutation is wrapped in AsyncSession.begin() context
        - On success: transaction is automatically committed
        - On failure: transaction is automatically rolled back
        - Operation is atomic; no partial state on failure
        
        Note:
            - Only works on projects with is_deleted=True
            - Returns generic error if project not found (avoids leaking team info)
        """
        try:
            # Establish transaction boundary for restore operation
            async with self.db.begin():
                restored_project = await self.repository.restore(
                    tenant_id, team_id, project_id
                )
                
                if not restored_project:
                    raise ProjectNotFoundError("Deleted project not found or access denied")
                
                self.logger.info(
                    "Project restored",
                    extra={
                        "project_id": project_id,
                        "team_id": team_id
                    }
                )
                
                # TODO: Call audit_service.log_restore() with project details
                
                return restored_project
        
        except RepositoryError as e:
            self.logger.error(
                "Failed to restore project",
                extra={"project_id": project_id, "team_id": team_id},
                exc_info=e
            )
            raise

    # ==================== INTERNAL HELPERS ====================

    @staticmethod
    def _serialize_project_snapshot(project: Project) -> dict:
        """
        Build JSON-compatible project snapshot for audit logs.

        Contains exactly:
        - id
        - tenant_id
        - team_id
        - name
        - description
        - status
        - created_at (ISO-8601 string or None)
        - updated_at (ISO-8601 string or None)
        - is_deleted
        """
        return {
            "id": project.id,
            "tenant_id": project.tenant_id,
            "team_id": project.team_id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            "is_deleted": project.is_deleted,
        }

    @staticmethod
    def _validate_integration_context(
        *,
        tenant_id: int,
        actor_user_id: int,
        actor_organisation_id: int,
        recipient_user_ids: list[int],
    ) -> None:
        """Validate required integration context for project mutations."""
        if actor_user_id <= 0:
            raise ValueError("Invalid actor_user_id: must be positive integer")
        if actor_organisation_id <= 0:
            raise ValueError("Invalid actor_organisation_id: must be positive integer")
        if actor_organisation_id != tenant_id:
            raise ValueError("actor_organisation_id must match tenant_id")
        if not recipient_user_ids:
            raise ValueError("recipient_user_ids must be non-empty")
        for recipient_id in recipient_user_ids:
            if recipient_id <= 0:
                raise ValueError("recipient_user_ids must contain only positive integers")
