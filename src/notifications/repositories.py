"""
Repository layer for Notification & Audit persistence operations.

This module follows repository conventions used by the existing Project repository:
- ORM-only SQLAlchemy access via AsyncSession
- Structured logging
- Specific repository exceptions
- Explicit tenant scoping in all query methods
- No hidden commits (flush allowed; commit controlled by service layer)

Architecture alignment:
model -> repository -> service -> controller/route
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, Notification

logger = logging.getLogger(__name__)


# =============================================================================
# Repository Exceptions
# =============================================================================

class NotificationAuditRepositoryError(Exception):
    """Base exception for notification/audit repository errors."""


class AuditLogCreateError(NotificationAuditRepositoryError):
    """Raised when audit log creation fails."""


class AuditLogQueryError(NotificationAuditRepositoryError):
    """Raised when audit log query fails."""


class NotificationCreateError(NotificationAuditRepositoryError):
    """Raised when notification creation fails."""


class NotificationQueryError(NotificationAuditRepositoryError):
    """Raised when notification query fails."""


class NotificationUpdateError(NotificationAuditRepositoryError):
    """Raised when notification read-status update fails."""


# =============================================================================
# Audit Repository
# =============================================================================

class AuditRepository:
    """
    Repository for append-only audit log access.

    Exposes creation/query operations only (no update/delete) to preserve
    append-only design at repository interface level.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_audit_log(
        self,
        *,
        tenant_id: int,
        event_type: str,
        entity_type: str,
        entity_id: int,
        actor_user_id: int,
        actor_organisation_id: int,
        previous_state: Optional[dict] = None,
        new_state: Optional[dict] = None,
    ) -> AuditLog:
        """
        Create a single audit log entry (append-only).

        Note:
            Uses flush() to persist and populate generated fields (e.g., id, timestamp),
            but intentionally does not commit.
        """
        logger.info(
            "audit_repository.create_audit_log.start",
            extra={
                "tenant_id": tenant_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor_user_id": actor_user_id,
                "actor_organisation_id": actor_organisation_id,
            },
        )

        audit_log = AuditLog(
            tenant_id=tenant_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            actor_organisation_id=actor_organisation_id,
            previous_state=previous_state,
            new_state=new_state,
        )

        try:
            self.db.add(audit_log)
            await self.db.flush()  # no commit; service controls transaction boundaries

            logger.info(
                "audit_repository.create_audit_log.success",
                extra={
                    "audit_log_id": audit_log.id,
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                },
            )
            return audit_log

        except IntegrityError as exc:
            logger.error(
                "audit_repository.create_audit_log.integrity_error",
                extra={
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "error": str(exc),
                },
            )
            raise AuditLogCreateError("Failed to create audit log due to data integrity violation") from exc

        except SQLAlchemyError as exc:
            logger.error(
                "audit_repository.create_audit_log.db_error",
                extra={
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "error": str(exc),
                },
            )
            raise AuditLogCreateError("Failed to create audit log due to database error") from exc

    async def get_audit_history_by_entity(
        self,
        *,
        tenant_id: int,
        entity_type: str,
        entity_id: int,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        event_type: Optional[str] = None,
    ) -> list[AuditLog]:
        """
        Get audit history for a given entity within tenant scope.

        Optional filters:
        - from_timestamp (inclusive)
        - to_timestamp (inclusive)
        - event_type (exact match)
        """
        logger.info(
            "audit_repository.get_audit_history_by_entity.start",
            extra={
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "from_timestamp": from_timestamp.isoformat() if from_timestamp else None,
                "to_timestamp": to_timestamp.isoformat() if to_timestamp else None,
                "event_type": event_type,
            },
        )

        conditions = [
            AuditLog.tenant_id == tenant_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        ]

        if from_timestamp is not None:
            conditions.append(AuditLog.timestamp >= from_timestamp)

        if to_timestamp is not None:
            conditions.append(AuditLog.timestamp <= to_timestamp)

        if event_type is not None:
            conditions.append(AuditLog.event_type == event_type)

        stmt = (
            select(AuditLog)
            .where(and_(*conditions))
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        )

        try:
            result = await self.db.execute(stmt)
            rows = result.scalars().all()

            logger.info(
                "audit_repository.get_audit_history_by_entity.success",
                extra={
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "count": len(rows),
                },
            )
            return rows

        except SQLAlchemyError as exc:
            logger.error(
                "audit_repository.get_audit_history_by_entity.db_error",
                extra={
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "error": str(exc),
                },
            )
            raise AuditLogQueryError("Failed to query audit history") from exc


# =============================================================================
# Notification Repository
# =============================================================================

class NotificationRepository:
    """
    Repository for notification persistence and tenant-scoped retrieval/update.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_notification(
        self,
        *,
        tenant_id: int,
        recipient_user_id: int,
        event_type: str,
        project_id: int,
        message: str,
    ) -> Notification:
        """
        Create a single notification.

        Uses flush() only; commit is controlled by service layer.
        """
        logger.info(
            "notification_repository.create_notification.start",
            extra={
                "tenant_id": tenant_id,
                "recipient_user_id": recipient_user_id,
                "event_type": event_type,
                "project_id": project_id,
            },
        )

        notification = Notification(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_type=event_type,
            project_id=project_id,
            message=message,
            read=False,
        )

        try:
            self.db.add(notification)
            await self.db.flush()

            logger.info(
                "notification_repository.create_notification.success",
                extra={
                    "notification_id": notification.id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                },
            )
            return notification

        except IntegrityError as exc:
            logger.error(
                "notification_repository.create_notification.integrity_error",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "event_type": event_type,
                    "project_id": project_id,
                    "error": str(exc),
                },
            )
            raise NotificationCreateError("Failed to create notification due to data integrity violation") from exc

        except SQLAlchemyError as exc:
            logger.error(
                "notification_repository.create_notification.db_error",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "event_type": event_type,
                    "project_id": project_id,
                    "error": str(exc),
                },
            )
            raise NotificationCreateError("Failed to create notification due to database error") from exc

    async def create_notifications_for_recipients(
        self,
        *,
        tenant_id: int,
        recipient_user_ids: Iterable[int],
        event_type: str,
        project_id: int,
        message: str,
    ) -> list[Notification]:
        """
        Create notifications for multiple resolved recipients.

        Uses flush() only; commit is controlled by service layer.
        """
        recipient_ids = list(dict.fromkeys(recipient_user_ids))  # de-duplicate, keep order

        logger.info(
            "notification_repository.create_notifications_for_recipients.start",
            extra={
                "tenant_id": tenant_id,
                "recipient_count": len(recipient_ids),
                "event_type": event_type,
                "project_id": project_id,
            },
        )

        notifications = [
            Notification(
                tenant_id=tenant_id,
                recipient_user_id=recipient_id,
                event_type=event_type,
                project_id=project_id,
                message=message,
                read=False,
            )
            for recipient_id in recipient_ids
        ]

        try:
            self.db.add_all(notifications)
            await self.db.flush()

            logger.info(
                "notification_repository.create_notifications_for_recipients.success",
                extra={
                    "tenant_id": tenant_id,
                    "created_count": len(notifications),
                    "event_type": event_type,
                    "project_id": project_id,
                },
            )
            return notifications

        except IntegrityError as exc:
            logger.error(
                "notification_repository.create_notifications_for_recipients.integrity_error",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_count": len(recipient_ids),
                    "event_type": event_type,
                    "project_id": project_id,
                    "error": str(exc),
                },
            )
            raise NotificationCreateError(
                "Failed to create notifications due to data integrity violation"
            ) from exc

        except SQLAlchemyError as exc:
            logger.error(
                "notification_repository.create_notifications_for_recipients.db_error",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_count": len(recipient_ids),
                    "event_type": event_type,
                    "project_id": project_id,
                    "error": str(exc),
                },
            )
            raise NotificationCreateError("Failed to create notifications due to database error") from exc

    async def get_unread_notifications_by_recipient(
        self,
        *,
        tenant_id: int,
        recipient_user_id: int,
    ) -> list[Notification]:
        """
        Return unread notifications for a recipient within tenant scope.
        """
        logger.info(
            "notification_repository.get_unread_notifications_by_recipient.start",
            extra={
                "tenant_id": tenant_id,
                "recipient_user_id": recipient_user_id,
            },
        )

        stmt = (
            select(Notification)
            .where(
                and_(
                    Notification.tenant_id == tenant_id,
                    Notification.recipient_user_id == recipient_user_id,
                    Notification.read.is_(False),
                )
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )

        try:
            result = await self.db.execute(stmt)
            rows = result.scalars().all()

            logger.info(
                "notification_repository.get_unread_notifications_by_recipient.success",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "count": len(rows),
                },
            )
            return rows

        except SQLAlchemyError as exc:
            logger.error(
                "notification_repository.get_unread_notifications_by_recipient.db_error",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "error": str(exc),
                },
            )
            raise NotificationQueryError("Failed to query unread notifications") from exc

    async def mark_notification_as_read(
        self,
        *,
        notification_id: int,
        tenant_id: int,
        recipient_user_id: int,
    ) -> Optional[Notification]:
        """
        Mark a notification as read only when tenant_id and recipient_user_id match.

        Returns:
            Notification if found within tenant+recipient scope, otherwise None.
        """
        logger.info(
            "notification_repository.mark_notification_as_read.start",
            extra={
                "notification_id": notification_id,
                "tenant_id": tenant_id,
                "recipient_user_id": recipient_user_id,
            },
        )

        stmt = select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.tenant_id == tenant_id,
                Notification.recipient_user_id == recipient_user_id,
            )
        )

        try:
            result = await self.db.execute(stmt)
            notification = result.scalar_one_or_none()

            if notification is None:
                logger.info(
                    "notification_repository.mark_notification_as_read.not_found",
                    extra={
                        "notification_id": notification_id,
                        "tenant_id": tenant_id,
                        "recipient_user_id": recipient_user_id,
                    },
                )
                return None

            notification.read = True
            await self.db.flush()

            logger.info(
                "notification_repository.mark_notification_as_read.success",
                extra={
                    "notification_id": notification.id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                },
            )
            return notification

        except SQLAlchemyError as exc:
            logger.error(
                "notification_repository.mark_notification_as_read.db_error",
                extra={
                    "notification_id": notification_id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "error": str(exc),
                },
            )
            raise NotificationUpdateError("Failed to mark notification as read") from exc
