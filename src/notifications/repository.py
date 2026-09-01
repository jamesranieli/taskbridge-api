"""
Repository layer for Notification model with multi-tenant isolation.

Tracks user notifications for project events.
"""

from typing import Optional, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import SQLAlchemyError

from .model import Notification

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """Base exception for repository-layer errors."""
    pass


class NotificationRepository:
    """
    Repository for Notification records with tenant isolation.
    
    Design:
    - All operations enforce tenant_id + recipient_user_id isolation
    - Read status updates verify both tenant and recipient ownership
    - No delete method; notifications persist (design choice for audit trail)
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
        notification_id: str,
        tenant_id: int,
        recipient_user_id: int,
        event_type: str,
        project_id: int,
        message: str
    ) -> Notification:
        """
        Create a new notification.
        
        Args:
            notification_id (str): UUID string for this notification
            tenant_id (int): Tenant ID for isolation (immutable)
            recipient_user_id (int): Target user ID
            event_type (str): Event type (project.created, project.status_updated, project.deleted)
            project_id (int): Project ID that triggered notification
            message (str): Human-readable summary (max 500 chars)
        
        Returns:
            Notification: Newly created notification
        
        Raises:
            RepositoryError: If database operation fails
        """
        try:
            notification = Notification(
                id=notification_id,
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
                event_type=event_type,
                project_id=project_id,
                message=message,
                read=False
            )
            self.db.add(notification)
            await self.db.flush()
            self.logger.info(
                "Notification created",
                extra={
                    "notification_id": notification_id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "event_type": event_type,
                    "project_id": project_id
                }
            )
            return notification
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error creating notification",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "event_type": event_type
                },
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def get_by_recipient(
        self,
        tenant_id: int,
        recipient_user_id: int,
        read: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Notification]:
        """
        Retrieve notifications for a user with optional read status filter.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            recipient_user_id (int): Target user ID
            read (bool): Optional filter by read status (True, False, or None for all)
            limit (int): Max results per page (1-1000)
            offset (int): Results to skip for pagination
        
        Returns:
            List[Notification]: Notifications matching criteria (empty list if none)
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            # Build filter conditions
            conditions = [
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == recipient_user_id
            ]
            
            if read is not None:
                conditions.append(Notification.read == read)
            
            # Execute query with ordering by created_at descending
            result = await self.db.execute(
                select(Notification)
                .where(and_(*conditions))
                .order_by(Notification.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            notifications = result.scalars().all()
            self.logger.debug(
                "Retrieved notifications by recipient",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "read": read,
                    "count": len(notifications)
                }
            )
            return notifications
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error retrieving notifications",
                extra={"tenant_id": tenant_id, "recipient_user_id": recipient_user_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def count_by_recipient(
        self,
        tenant_id: int,
        recipient_user_id: int,
        read: Optional[bool] = None
    ) -> int:
        """
        Count notifications for a user with optional read status filter.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            recipient_user_id (int): Target user ID
            read (bool): Optional filter by read status
        
        Returns:
            int: Total count of matching notifications
        
        Raises:
            RepositoryError: If database query fails
        """
        try:
            # Build filter conditions
            conditions = [
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == recipient_user_id
            ]
            
            if read is not None:
                conditions.append(Notification.read == read)
            
            result = await self.db.execute(
                select(Notification).where(and_(*conditions))
            )
            count = len(result.scalars().all())
            return count
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error counting notifications",
                extra={"tenant_id": tenant_id, "recipient_user_id": recipient_user_id},
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
    
    async def mark_read(
        self,
        tenant_id: int,
        recipient_user_id: int,
        notification_id: str
    ) -> Optional[Notification]:
        """
        Mark a notification as read with tenant + recipient isolation.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            recipient_user_id (int): Recipient user ID (must own the notification)
            notification_id (str): Notification ID to mark as read
        
        Returns:
            Optional[Notification]: Updated notification; None if not found or not owned by recipient
        
        Raises:
            RepositoryError: If database operation fails
        """
        try:
            # Fetch notification with isolation
            result = await self.db.execute(
                select(Notification).where(
                    and_(
                        Notification.id == notification_id,
                        Notification.tenant_id == tenant_id,
                        Notification.recipient_user_id == recipient_user_id
                    )
                )
            )
            notification = result.scalar_one_or_none()
            if not notification:
                self.logger.warning(
                    "Notification not found for mark_read (isolation enforced)",
                    extra={
                        "notification_id": notification_id,
                        "tenant_id": tenant_id,
                        "recipient_user_id": recipient_user_id
                    }
                )
                return None
            
            notification.read = True
            await self.db.flush()
            self.logger.info(
                "Notification marked as read",
                extra={
                    "notification_id": notification_id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id
                }
            )
            return notification
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error marking notification as read",
                extra={
                    "notification_id": notification_id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id
                },
                exc_info=e
            )
            raise RepositoryError(f"Database error: {str(e)}") from e
