"""
Repository layer for Audit model with read-only data access.

Immutable audit records with filtering support.
"""

from typing import Optional, List
from datetime import datetime
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.exc import SQLAlchemyError

from .model import Audit

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """Base exception for repository-layer errors."""
    pass


class AuditRepository:
    """
    Read-only repository for Audit records with filtering.
    
    Design:
    - No update or delete methods; audit records are immutable
    - All queries enforce tenant_id isolation
    - Supports optional date-range and event-type filtering
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
        audit_id: str,
        tenant_id: int,
        event_type: str,
        entity_type: str,
        entity_id: int,
        actor_user_id: int,
        actor_org_id: int,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        actor_ip: Optional[str] = None
    ) -> Audit:
        """
        Create a new immutable audit record.
        
        Args:
            audit_id (str): UUID string for this audit event
            tenant_id (int): Tenant ID for isolation
            event_type (str): Event type (project.created, project.status_updated, project.deleted, MILESTONE_REOPENED)
            entity_type (str): Entity type (currently: project)
            entity_id (int): Entity ID (Project ID)
            actor_user_id (int): User ID who triggered the mutation
            actor_org_id (int): Organization ID of actor
            before_state (dict): Previous state (optional)
            after_state (dict): New state (optional)
            actor_ip (str): Optional IP address of actor
        
        Returns:
            Audit: Newly created audit record
        
        Raises:
            RepositoryError: If database operation fails
        """
        try:
            audit = Audit(
                id=audit_id,
                tenant_id=tenant_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_org_id=actor_org_id,
                before_state=before_state,
                after_state=after_state,
                actor_ip=actor_ip
            )
            self.db.add(audit)
            await self.db.flush()
            self.logger.info(
                "Audit record created",
                extra={
                    "audit_id": audit_id,
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "entity_id": entity_id,
                    "ip_captured": actor_ip is not None
                }
            )
            return audit
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error creating audit record",
                extra={"tenant_id": tenant_id, "event_type": event_type},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def get_history(
        self,
        tenant_id: int,
        entity_id: int,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Audit]:
        """
        Retrieve audit history for an entity with optional filtering.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            entity_id (int): Entity ID to retrieve history for (Project ID)
            event_type (str): Optional event type filter
            start_date (datetime): Optional start of date range (inclusive)
            end_date (datetime): Optional end of date range (inclusive)
            limit (int): Max results per page (1-1000)
            offset (int): Results to skip for pagination
        
        Returns:
            List[Audit]: Audit records matching criteria (empty list if none)
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            # Build filter conditions
            conditions = [
                Audit.tenant_id == tenant_id,
                Audit.entity_id == entity_id
            ]
            
            if event_type:
                conditions.append(Audit.event_type == event_type)
            
            if start_date:
                conditions.append(Audit.timestamp >= start_date)
            
            if end_date:
                conditions.append(Audit.timestamp <= end_date)
            
            # Execute query with ordering by timestamp descending
            result = await self.db.execute(
                select(Audit)
                .where(and_(*conditions))
                .order_by(Audit.timestamp.desc())
                .limit(limit)
                .offset(offset)
            )
            audits = result.scalars().all()
            self.logger.debug(
                "Retrieved audit history",
                extra={
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "event_type": event_type,
                    "count": len(audits)
                }
            )
            return audits
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error retrieving audit history",
                extra={"tenant_id": tenant_id, "entity_id": entity_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def count_history(
        self,
        tenant_id: int,
        entity_id: int,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """
        Count audit records for an entity with optional filtering.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            entity_id (int): Entity ID (Project ID)
            event_type (str): Optional event type filter
            start_date (datetime): Optional start date (inclusive)
            end_date (datetime): Optional end date (inclusive)
        
        Returns:
            int: Total count of matching audit records
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            # Build filter conditions
            conditions = [
                Audit.tenant_id == tenant_id,
                Audit.entity_id == entity_id
            ]
            
            if event_type:
                conditions.append(Audit.event_type == event_type)
            
            if start_date:
                conditions.append(Audit.timestamp >= start_date)
            
            if end_date:
                conditions.append(Audit.timestamp <= end_date)
            
            result = await self.db.execute(
                select(func.count(Audit.id)).where(and_(*conditions))
            )
            count = result.scalar_one()
            return count or 0
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error counting audit records",
                extra={"tenant_id": tenant_id, "entity_id": entity_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
