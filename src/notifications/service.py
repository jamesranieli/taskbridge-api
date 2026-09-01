"""
Service layer for Notification business logic.

Creates and manages user notifications for project events.
"""

import logging
import uuid
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from .model import Notification
from .repository import NotificationRepository, RepositoryError

logger = logging.getLogger(__name__)


class NotificationValidationError(Exception):
    """Raised when notification validation fails."""
    pass


class NotificationService:
    """
    Service layer for notification creation and retrieval.
    
    Enforces:
    - All required fields validated before creation
    - Multi-tenant isolation on all operations
    - Bulk recipient notification creation
    - Read status updates only by intended recipient
    """
    
    VALID_EVENT_TYPES = frozenset([
        "project.created",
        "project.status_updated",
        "project.deleted"
    ])
    MAX_MESSAGE_LENGTH = 500
    
    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session."""
        self.db = db
        self.repository = NotificationRepository(db)
    
    async def create_for_recipients(
        self,
        tenant_id: int,
        recipient_user_ids: List[int],
        event_type: str,
        project_id: int,
        message: str
    ) -> List[Notification]:
        """
        Create notifications for multiple recipients.
        
        All recipients receive the same event, project, and message.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            recipient_user_ids (list): User IDs to receive notification
            event_type (str): Event type (project.created, project.status_updated, project.deleted)
            project_id (int): Project ID that triggered notification
            message (str): Human-readable summary (max 500 chars)
        
        Returns:
            List[Notification]: Newly created notifications
        
        Raises:
            NotificationValidationError: If validation fails
            RepositoryError: If database operation fails
        """
        # Validate event_type
        if event_type not in self.VALID_EVENT_TYPES:
            raise NotificationValidationError(
                f"Invalid event_type '{event_type}'. Must be one of: {', '.join(sorted(self.VALID_EVENT_TYPES))}"
            )
        
        # Validate message
        if not message or not message.strip():
            raise NotificationValidationError("Message cannot be empty")
        
        message_stripped = message.strip()
        if len(message_stripped) > self.MAX_MESSAGE_LENGTH:
            raise NotificationValidationError(
                f"Message must be {self.MAX_MESSAGE_LENGTH} characters or less"
            )
        
        # Validate required fields
        if not isinstance(project_id, int) or project_id <= 0:
            raise NotificationValidationError("project_id must be a positive integer")
        
        if not recipient_user_ids or len(recipient_user_ids) == 0:
            raise NotificationValidationError("recipient_user_ids cannot be empty")
        
        if not all(isinstance(uid, int) and uid > 0 for uid in recipient_user_ids):
            raise NotificationValidationError("All recipient_user_ids must be positive integers")
        
        notifications = []
        try:
            async with self.db.begin():
                for recipient_user_id in recipient_user_ids:
                    notification_id = str(uuid.uuid4())
                    notification = await self.repository.create(
                        notification_id=notification_id,
                        tenant_id=tenant_id,
                        recipient_user_id=recipient_user_id,
                        event_type=event_type,
                        project_id=project_id,
                        message=message_stripped
                    )
                    notifications.append(notification)
                
                logger.info(
                    "Bulk notifications created",
                    extra={
                        "tenant_id": tenant_id,
                        "event_type": event_type,
                        "project_id": project_id,
                        "recipient_count": len(recipient_user_ids)
                    }
                )
            return notifications
        except RepositoryError as e:
            logger.error(
                "Failed to create notifications",
                extra={"tenant_id": tenant_id, "event_type": event_type},
                exc_info=e
            )
            raise
    
    async def get_user_notifications(
        self,
        tenant_id: int,
        recipient_user_id: int,
        read: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> tuple[List[Notification], int]:
        """
        Retrieve notifications for a user with optional read status filter.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            recipient_user_id (int): User ID to retrieve notifications for
            read (bool): Optional filter by read status (True, False, or None for all)
            limit (int): Max results per page (1-1000)
            offset (int): Results to skip for pagination
        
        Returns:
            Tuple of (notifications list, total count)
        
        Raises:
            RepositoryError: If database query fails
        """
        if not (1 <= limit <= 1000):
            raise ValueError("limit must be between 1 and 1000")
        
        if offset < 0:
            raise ValueError("offset must be non-negative")
        
        try:
            notifications = await self.repository.get_by_recipient(
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
                read=read,
                limit=limit,
                offset=offset
            )
            total = await self.repository.count_by_recipient(
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
                read=read
            )
            logger.debug(
                "Retrieved user notifications",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "read": read,
                    "count": len(notifications),
                    "total": total
                }
            )
            return notifications, total
        except RepositoryError as e:
            logger.error(
                "Failed to retrieve user notifications",
                extra={"tenant_id": tenant_id, "recipient_user_id": recipient_user_id},
                exc_info=e
            )
            raise
    
    async def mark_notification_read(
        self,
        tenant_id: int,
        recipient_user_id: int,
        notification_id: str
    ) -> Notification:
        """
        Mark a notification as read.
        
        Args:
            tenant_id (int): Tenant ID for isolation
            recipient_user_id (int): User ID (must own the notification)
            notification_id (str): Notification ID to mark as read
        
        Returns:
            Notification: Updated notification
        
        Raises:
            NotificationValidationError: If notification not found or not owned by user
            RepositoryError: If database operation fails
        """
        try:
            async with self.db.begin():
                notification = await self.repository.mark_read(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    notification_id=notification_id
                )
                if not notification:
                    raise NotificationValidationError(
                        "Notification not found or access denied"
                    )
                
                logger.info(
                    "Notification marked as read",
                    extra={
                        "notification_id": notification_id,
                        "tenant_id": tenant_id,
                        "recipient_user_id": recipient_user_id
                    }
                )
                return notification
        except RepositoryError as e:
            logger.error(
                "Failed to mark notification as read",
                extra={
                    "notification_id": notification_id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id
                },
                exc_info=e
            )
            raise
