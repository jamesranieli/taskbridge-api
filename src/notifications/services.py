"""
Service layer for Notification & Audit domain logic.

Architecture alignment:
model -> repository -> service -> controller/route

This service module:
- validates input and business rules from SPEC.md
- enforces audit append-only behavior at service surface (create/query only)
- translates repository exceptions into service exceptions
- orchestrates repository operations without committing or rolling back
- keeps recipient resolution as an external integration boundary (accepts resolved recipient IDs)

Transaction ownership:
- repositories perform flush-only writes
- these domain services do not commit or rollback
- outer orchestration layer owns the full transaction boundary so related
  operations (e.g., Project + Audit + Notifications) are atomic together
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, Notification
from .repositories import (
    AuditLogCreateError,
    AuditLogQueryError,
    AuditRepository,
    NotificationCreateError,
    NotificationQueryError,
    NotificationRepository,
    NotificationUpdateError,
)

logger = logging.getLogger(__name__)

SUPPORTED_EVENT_TYPES = {
    "project_created",
    "project_status_updated",
    "project_deleted",
}
SUPPORTED_ENTITY_TYPES = {"project"}
MAX_NOTIFICATION_MESSAGE_LENGTH = 1000


# =============================================================================
# Service Exceptions
# =============================================================================

class NotificationAuditServiceError(Exception):
    """Base exception for notification/audit service errors."""


class ValidationServiceError(NotificationAuditServiceError):
    """Raised when input validation fails."""


class AuditCreateServiceError(NotificationAuditServiceError):
    """Raised when audit creation fails."""


class AuditQueryServiceError(NotificationAuditServiceError):
    """Raised when audit history query fails."""


class NotificationCreateServiceError(NotificationAuditServiceError):
    """Raised when notification creation fails."""


class NotificationQueryServiceError(NotificationAuditServiceError):
    """Raised when notification query fails."""


class NotificationReadUpdateServiceError(NotificationAuditServiceError):
    """Raised when notification read-status update fails."""


class NotificationNotFoundOrUnauthorizedServiceError(NotificationAuditServiceError):
    """
    Raised when a notification cannot be found under tenant+recipient scope.

    Authorization-safe: does not disclose whether notification exists outside scope.
    """


# =============================================================================
# Audit Service
# =============================================================================

class AuditService:
    """
    Service for audit append-only operations.

    Exposes create/query methods only to enforce append-only immutability policy.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuditRepository(db)

    async def create_audit_entry(
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
        Create an audit entry for project lifecycle events.

        Validations:
        - positive IDs
        - supported event_type
        - supported entity_type for current use
        - actor_organisation_id must match tenant_id for project audit events

        Transaction behavior:
        - repository performs flush only
        - this service does not commit/rollback
        - outer orchestration layer controls transaction boundaries
        """
        logger.info(
            "audit_service.create_audit_entry.start",
            extra={
                "tenant_id": tenant_id,
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "actor_user_id": actor_user_id,
                "actor_organisation_id": actor_organisation_id,
            },
        )

        self._validate_positive_id(tenant_id, "tenant_id")
        self._validate_positive_id(entity_id, "entity_id")
        self._validate_positive_id(actor_user_id, "actor_user_id")
        self._validate_positive_id(actor_organisation_id, "actor_organisation_id")
        self._validate_event_type(event_type)
        self._validate_entity_type(entity_type)

        if actor_organisation_id != tenant_id:
            raise ValidationServiceError(
                "actor_organisation_id must match tenant_id for project audit events"
            )

        self._validate_snapshot(previous_state, "previous_state")
        self._validate_snapshot(new_state, "new_state")

        try:
            audit_log = await self.repo.create_audit_log(
                tenant_id=tenant_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_organisation_id=actor_organisation_id,
                previous_state=previous_state,
                new_state=new_state,
            )

            logger.info(
                "audit_service.create_audit_entry.success",
                extra={
                    "audit_log_id": audit_log.id,
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                },
            )
            return audit_log

        except AuditLogCreateError as exc:
            logger.error(
                "audit_service.create_audit_entry.repo_error",
                extra={
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "error": str(exc),
                },
            )
            raise AuditCreateServiceError("Failed to create audit entry") from exc

    async def get_audit_history(
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
        Get audit history for an entity within tenant scope.

        Optional filters:
        - from_timestamp (inclusive)
        - to_timestamp (inclusive)
        - event_type (exact match)
        """
        logger.info(
            "audit_service.get_audit_history.start",
            extra={
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "from_timestamp": from_timestamp.isoformat() if from_timestamp else None,
                "to_timestamp": to_timestamp.isoformat() if to_timestamp else None,
                "event_type": event_type,
            },
        )

        self._validate_positive_id(tenant_id, "tenant_id")
        self._validate_positive_id(entity_id, "entity_id")
        self._validate_entity_type(entity_type)

        if event_type is not None:
            self._validate_event_type(event_type)

        if from_timestamp and to_timestamp and from_timestamp > to_timestamp:
            raise ValidationServiceError("from_timestamp must be less than or equal to to_timestamp")

        try:
            rows = await self.repo.get_audit_history_by_entity(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                from_timestamp=from_timestamp,
                to_timestamp=to_timestamp,
                event_type=event_type,
            )

            logger.info(
                "audit_service.get_audit_history.success",
                extra={
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "count": len(rows),
                },
            )
            return rows

        except AuditLogQueryError as exc:
            logger.error(
                "audit_service.get_audit_history.repo_error",
                extra={
                    "tenant_id": tenant_id,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "error": str(exc),
                },
            )
            raise AuditQueryServiceError("Failed to retrieve audit history") from exc

    @staticmethod
    def _validate_positive_id(value: int, field_name: str) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValidationServiceError(f"{field_name} must be a positive integer")

    @staticmethod
    def _validate_event_type(event_type: str) -> None:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValidationServiceError("event_type must be a non-empty string")
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValidationServiceError(
                "Unsupported event_type. Allowed values: "
                "project_created, project_status_updated, project_deleted"
            )

    @staticmethod
    def _validate_entity_type(entity_type: str) -> None:
        if not isinstance(entity_type, str) or not entity_type.strip():
            raise ValidationServiceError("entity_type must be a non-empty string")
        if entity_type not in SUPPORTED_ENTITY_TYPES:
            raise ValidationServiceError("Unsupported entity_type. Allowed value: project")

    @staticmethod
    def _validate_snapshot(snapshot: Optional[dict], field_name: str) -> None:
        if snapshot is not None and not isinstance(snapshot, dict):
            raise ValidationServiceError(f"{field_name} must be an object or null")


# =============================================================================
# Notification Service
# =============================================================================

class NotificationService:
    """
    Service for notification creation/query/read operations.

    Recipient resolution is an integration boundary:
    this service accepts already-resolved recipient_user_ids.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)

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
        Create notifications for resolved recipient user IDs.

        Validations:
        - positive tenant/project/recipient IDs
        - supported event_type
        - bounded, non-empty message
        - recipient de-duplication preserved via repository behavior

        Transaction behavior:
        - repository performs flush only
        - this service does not commit/rollback
        - outer orchestration layer controls transaction boundaries
        """
        recipient_list = list(recipient_user_ids)

        logger.info(
            "notification_service.create_notifications_for_recipients.start",
            extra={
                "tenant_id": tenant_id,
                "recipient_count": len(recipient_list),
                "event_type": event_type,
                "project_id": project_id,
            },
        )

        self._validate_positive_id(tenant_id, "tenant_id")
        self._validate_positive_id(project_id, "project_id")
        self._validate_event_type(event_type)
        self._validate_message(message)

        if not recipient_list:
            raise ValidationServiceError("recipient_user_ids must contain at least one user ID")

        for rid in recipient_list:
            self._validate_positive_id(rid, "recipient_user_id")

        try:
            notifications = await self.repo.create_notifications_for_recipients(
                tenant_id=tenant_id,
                recipient_user_ids=recipient_list,
                event_type=event_type,
                project_id=project_id,
                message=message.strip(),
            )

            logger.info(
                "notification_service.create_notifications_for_recipients.success",
                extra={
                    "tenant_id": tenant_id,
                    "created_count": len(notifications),
                    "event_type": event_type,
                    "project_id": project_id,
                },
            )
            return notifications

        except NotificationCreateError as exc:
            logger.error(
                "notification_service.create_notifications_for_recipients.repo_error",
                extra={
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "project_id": project_id,
                    "error": str(exc),
                },
            )
            raise NotificationCreateServiceError("Failed to create notifications") from exc

    async def get_unread_notifications_for_user(
        self,
        *,
        tenant_id: int,
        recipient_user_id: int,
    ) -> list[Notification]:
        """
        Get unread notifications for one user within tenant scope.
        """
        logger.info(
            "notification_service.get_unread_notifications_for_user.start",
            extra={
                "tenant_id": tenant_id,
                "recipient_user_id": recipient_user_id,
            },
        )

        self._validate_positive_id(tenant_id, "tenant_id")
        self._validate_positive_id(recipient_user_id, "recipient_user_id")

        try:
            rows = await self.repo.get_unread_notifications_by_recipient(
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
            )

            logger.info(
                "notification_service.get_unread_notifications_for_user.success",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "count": len(rows),
                },
            )
            return rows

        except NotificationQueryError as exc:
            logger.error(
                "notification_service.get_unread_notifications_for_user.repo_error",
                extra={
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "error": str(exc),
                },
            )
            raise NotificationQueryServiceError("Failed to retrieve unread notifications") from exc

    async def mark_notification_as_read(
        self,
        *,
        notification_id: int,
        tenant_id: int,
        recipient_user_id: int,
    ) -> Notification:
        """
        Mark notification as read when notification_id + tenant_id + recipient_user_id match.

        Raises NotificationNotFoundOrUnauthorizedServiceError when no scoped record matches.
        """
        logger.info(
            "notification_service.mark_notification_as_read.start",
            extra={
                "notification_id": notification_id,
                "tenant_id": tenant_id,
                "recipient_user_id": recipient_user_id,
            },
        )

        self._validate_positive_id(notification_id, "notification_id")
        self._validate_positive_id(tenant_id, "tenant_id")
        self._validate_positive_id(recipient_user_id, "recipient_user_id")

        try:
            notification = await self.repo.mark_notification_as_read(
                notification_id=notification_id,
                tenant_id=tenant_id,
                recipient_user_id=recipient_user_id,
            )

            if notification is None:
                logger.info(
                    "notification_service.mark_notification_as_read.not_found_or_unauthorized",
                    extra={
                        "notification_id": notification_id,
                        "tenant_id": tenant_id,
                        "recipient_user_id": recipient_user_id,
                    },
                )
                raise NotificationNotFoundOrUnauthorizedServiceError(
                    "Notification not found or not authorized for this tenant/user scope"
                )

            logger.info(
                "notification_service.mark_notification_as_read.success",
                extra={
                    "notification_id": notification.id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                },
            )
            return notification

        except NotificationNotFoundOrUnauthorizedServiceError:
            raise

        except NotificationUpdateError as exc:
            logger.error(
                "notification_service.mark_notification_as_read.repo_error",
                extra={
                    "notification_id": notification_id,
                    "tenant_id": tenant_id,
                    "recipient_user_id": recipient_user_id,
                    "error": str(exc),
                },
            )
            raise NotificationReadUpdateServiceError("Failed to update notification read status") from exc

    @staticmethod
    def _validate_positive_id(value: int, field_name: str) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValidationServiceError(f"{field_name} must be a positive integer")

    @staticmethod
    def _validate_event_type(event_type: str) -> None:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValidationServiceError("event_type must be a non-empty string")
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValidationServiceError(
                "Unsupported event_type. Allowed values: "
                "project_created, project_status_updated, project_deleted"
            )

    @staticmethod
    def _validate_message(message: str) -> None:
        if not isinstance(message, str):
            raise ValidationServiceError("message must be a string")
        trimmed = message.strip()
        if not trimmed:
            raise ValidationServiceError("message must be a non-empty string")
        if len(trimmed) > MAX_NOTIFICATION_MESSAGE_LENGTH:
            raise ValidationServiceError(
                f"message must be <= {MAX_NOTIFICATION_MESSAGE_LENGTH} characters"
            )
