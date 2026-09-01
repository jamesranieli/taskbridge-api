"""
Service layer for Audit business logic.

Creates immutable audit events with validation and isolation.
"""

import logging
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from .model import Audit
from .repository import AuditRepository, RepositoryError

logger = logging.getLogger(__name__)


class AuditValidationError(Exception):
    """Raised when audit event validation fails."""
    pass


class AuditService:
    """
    Service layer for immutable audit event creation and retrieval.
    
    Enforces:
    - actor_org_id equals tenant_id (actor belongs to tenant)
    - All required fields present and valid
    - Immutability (no updates or deletes)
    - Multi-tenant isolation
    """
    
    VALID_EVENT_TYPES = frozenset([
        "project.created",
        "project.status_updated",
        "project.deleted"
    ])
    VALID_ENTITY_TYPES = frozenset(["project"])
    
    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session."""
        self.db = db
        self.repository = AuditRepository(db)
    
    async def create_event(
        self,
        tenant_id: int,
        event_type: str,
        entity_type: str,
        entity_id: int,
        actor_user_id: int,
        actor_org_id: int,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None
    ) -> Audit:
        """
        Create an immutable audit event.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            event_type (str): Event type (project.created, project.status_updated, project.deleted)
            entity_type (str): Entity type (project)
            entity_id (int): Entity ID (Project ID)
            actor_user_id (int): User ID who triggered the mutation
            actor_org_id (int): Organization ID of actor (must equal tenant_id)
            before_state (dict): Previous state (optional)
            after_state (dict): New state (optional)
        
        Returns:
            Audit: Newly created audit record
        
        Raises:
            AuditValidationError: If validation fails
            RepositoryError: If database operation fails
        """
        # Validate event_type
        if event_type not in self.VALID_EVENT_TYPES:
            raise AuditValidationError(
                f"Invalid event_type '{event_type}'. Must be one of: {', '.join(sorted(self.VALID_EVENT_TYPES))}"
            )
        
        # Validate entity_type
        if entity_type not in self.VALID_ENTITY_TYPES:
            raise AuditValidationError(
                f"Invalid entity_type '{entity_type}'. Must be one of: {', '.join(sorted(self.VALID_ENTITY_TYPES))}"
            )
        
        # Validate actor_org_id equals tenant_id (multi-tenant isolation)
        if actor_org_id != tenant_id:
            raise AuditValidationError(
                f"actor_org_id ({actor_org_id}) must equal tenant_id ({tenant_id})"
            )
        
        # Validate required integer fields
        if not isinstance(entity_id, int) or entity_id <= 0:
            raise AuditValidationError("entity_id must be a positive integer")
        
        if not isinstance(actor_user_id, int) or actor_user_id <= 0:
            raise AuditValidationError("actor_user_id must be a positive integer")
        
        try:
            # Generate UUID for audit record
            audit_id = str(uuid.uuid4())
            
            async with self.db.begin():
                audit = await self.repository.create(
                    audit_id=audit_id,
                    tenant_id=tenant_id,
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    actor_user_id=actor_user_id,
                    actor_org_id=actor_org_id,
                    before_state=before_state,
                    after_state=after_state
                )
                logger.info(
                    "Audit event created",
                    extra={
                        "audit_id": audit_id,
                        "tenant_id": tenant_id,
                        "event_type": event_type,
                        "entity_id": entity_id,
                        "actor_user_id": actor_user_id
                    }
                )
                return audit
        except RepositoryError as e:
            logger.error(
                "Failed to create audit event",
                extra={"tenant_id": tenant_id, "event_type": event_type},
                exc_info=e
            )
            raise
    
    async def get_project_history(
        self,
        tenant_id: int,
        project_id: int,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[list[Audit], int]:
        """
        Retrieve audit history for a project with optional filtering.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            project_id (int): Project ID to retrieve history for
            event_type (str): Optional event type filter
            start_date (datetime): Optional start date (inclusive)
            end_date (datetime): Optional end date (inclusive)
            limit (int): Max results per page (1-1000)
            offset (int): Results to skip for pagination
        
        Returns:
            Tuple of (audit records list, total count)
        
        Raises:
            RepositoryError: If database query fails
        """
        if not (1 <= limit <= 1000):
            raise ValueError("limit must be between 1 and 1000")
        
        if offset < 0:
            raise ValueError("offset must be non-negative")
        
        # Validate date range if provided
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must be <= end_date")
        
        try:
            audits = await self.repository.get_history(
                tenant_id=tenant_id,
                entity_id=project_id,
                event_type=event_type,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                offset=offset
            )
            total = await self.repository.count_history(
                tenant_id=tenant_id,
                entity_id=project_id,
                event_type=event_type,
                start_date=start_date,
                end_date=end_date
            )
            logger.debug(
                "Retrieved project audit history",
                extra={
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "event_type": event_type,
                    "count": len(audits),
                    "total": total
                }
            )
            return audits, total
        except RepositoryError as e:
            logger.error(
                "Failed to retrieve audit history",
                extra={"tenant_id": tenant_id, "project_id": project_id},
                exc_info=e
            )
            raise
