"""
FastAPI controller/routes for Notification & Audit service.

Controller responsibilities:
- parse/validate HTTP request data
- resolve trusted caller organization context from X-Organisation-ID header
- call service layer
- map service exceptions to HTTP responses
- own transaction boundaries for standalone write endpoints

Business rules remain in service layer.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.projects.database import get_db
from .schemas import (
    AuditCreateRequest,
    AuditListResponse,
    AuditResponse,
    MarkNotificationReadRequest,
    NotificationListResponse,
    NotificationResponse,
)
from .services import (
    AuditCreateServiceError,
    AuditQueryServiceError,
    AuditService,
    NotificationNotFoundOrUnauthorizedServiceError,
    NotificationQueryServiceError,
    NotificationReadUpdateServiceError,
    NotificationService,
    ValidationServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["notifications-audit"])


def get_caller_organisation_id(
    x_organisation_id: int = Header(..., alias="X-Organisation-ID"),
) -> int:
    """
    Trusted request-context dependency for caller organization/tenant scope.

    Reads X-Organisation-ID header and enforces positive integer constraint.
    """
    if x_organisation_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="X-Organisation-ID must be a positive integer",
        )
    return x_organisation_id


@router.post(
    "/audit",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create audit log entry (internal)",
)
async def create_audit(
    payload: AuditCreateRequest,
    caller_organisation_id: int = Depends(get_caller_organisation_id),
    db: AsyncSession = Depends(get_db),
) -> AuditResponse:
    """
    Internal endpoint for trusted service-to-service audit creation.

    Enforces that payload tenant context matches trusted caller organization context.
    Client does not supply timestamp; server generates it.
    """
    logger.info(
        "notifications_controller.create_audit.start",
        extra={
            "caller_organisation_id": caller_organisation_id,
            "tenant_id": payload.tenant_id,
            "event_type": payload.event_type,
            "entity_type": payload.entity_type,
            "entity_id": payload.entity_id,
            "actor_user_id": payload.actor_user_id,
            "actor_organisation_id": payload.actor_organisation_id,
        },
    )

    if payload.tenant_id != caller_organisation_id or payload.actor_organisation_id != caller_organisation_id:
        logger.info(
            "notifications_controller.create_audit.forbidden_org_mismatch",
            extra={
                "caller_organisation_id": caller_organisation_id,
                "payload_tenant_id": payload.tenant_id,
                "payload_actor_organisation_id": payload.actor_organisation_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden for organization context",
        )

    service = AuditService(db)

    try:
        audit = await service.create_audit_entry(
            tenant_id=caller_organisation_id,
            event_type=payload.event_type,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            actor_user_id=payload.actor_user_id,
            actor_organisation_id=payload.actor_organisation_id,
            previous_state=payload.previous_state,
            new_state=payload.new_state,
        )
        await db.commit()

        logger.info(
            "notifications_controller.create_audit.success",
            extra={"audit_id": audit.id, "tenant_id": caller_organisation_id},
        )
        return AuditResponse.model_validate(audit)

    except ValidationServiceError as exc:
        await db.rollback()
        logger.warning(
            "notifications_controller.create_audit.validation_error",
            extra={"error": str(exc), "tenant_id": caller_organisation_id},
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    except AuditCreateServiceError as exc:
        await db.rollback()
        logger.error(
            "notifications_controller.create_audit.create_error",
            extra={"error": str(exc), "tenant_id": caller_organisation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create audit entry",
        ) from exc

    except Exception as exc:
        await db.rollback()
        logger.exception(
            "notifications_controller.create_audit.unexpected_error",
            extra={"tenant_id": caller_organisation_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while creating audit entry",
        ) from exc


@router.get(
    "/audit/{projectId}",
    response_model=AuditListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get audit history for project",
)
async def get_audit_history(
    projectId: int,
    caller_organisation_id: int = Depends(get_caller_organisation_id),
    from_timestamp: Optional[datetime] = Query(
        None, alias="from", description="Inclusive lower bound timestamp (UTC ISO-8601)"
    ),
    to_timestamp: Optional[datetime] = Query(
        None, alias="to", description="Inclusive upper bound timestamp (UTC ISO-8601)"
    ),
    eventType: Optional[str] = Query(None, description="Optional event type filter"),
    db: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    """
    Retrieve tenant-scoped audit history for a project with optional filters.

    Tenant context is exclusively derived from trusted X-Organisation-ID header.
    """
    logger.info(
        "notifications_controller.get_audit_history.start",
        extra={
            "tenant_id": caller_organisation_id,
            "project_id": projectId,
            "from_timestamp": from_timestamp.isoformat() if from_timestamp else None,
            "to_timestamp": to_timestamp.isoformat() if to_timestamp else None,
            "event_type": eventType,
        },
    )

    service = AuditService(db)

    try:
        rows = await service.get_audit_history(
            tenant_id=caller_organisation_id,
            entity_type="project",
            entity_id=projectId,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            event_type=eventType,
        )

        response = AuditListResponse(
            data=[AuditResponse.model_validate(r) for r in rows],
            total=len(rows),
        )

        logger.info(
            "notifications_controller.get_audit_history.success",
            extra={
                "tenant_id": caller_organisation_id,
                "project_id": projectId,
                "count": response.total,
            },
        )
        return response

    except ValidationServiceError as exc:
        logger.warning(
            "notifications_controller.get_audit_history.validation_error",
            extra={"error": str(exc), "tenant_id": caller_organisation_id, "project_id": projectId},
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    except AuditQueryServiceError as exc:
        logger.error(
            "notifications_controller.get_audit_history.query_error",
            extra={"error": str(exc), "tenant_id": caller_organisation_id, "project_id": projectId},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve audit history",
        ) from exc

    except Exception as exc:
        logger.exception(
            "notifications_controller.get_audit_history.unexpected_error",
            extra={"tenant_id": caller_organisation_id, "project_id": projectId},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while retrieving audit history",
        ) from exc


@router.get(
    "/notifications/{userId}",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get unread notifications for user",
)
async def get_unread_notifications(
    userId: int,
    caller_organisation_id: int = Depends(get_caller_organisation_id),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    """
    Return unread notifications for a recipient user within caller organization scope.
    """
    logger.info(
        "notifications_controller.get_unread_notifications.start",
        extra={"tenant_id": caller_organisation_id, "recipient_user_id": userId},
    )

    service = NotificationService(db)

    try:
        rows = await service.get_unread_notifications_for_user(
            tenant_id=caller_organisation_id,
            recipient_user_id=userId,
        )

        response = NotificationListResponse(
            data=[NotificationResponse.model_validate(r) for r in rows],
            total=len(rows),
        )

        logger.info(
            "notifications_controller.get_unread_notifications.success",
            extra={
                "tenant_id": caller_organisation_id,
                "recipient_user_id": userId,
                "count": response.total,
            },
        )
        return response

    except ValidationServiceError as exc:
        logger.warning(
            "notifications_controller.get_unread_notifications.validation_error",
            extra={"error": str(exc), "tenant_id": caller_organisation_id, "recipient_user_id": userId},
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    except NotificationQueryServiceError as exc:
        logger.error(
            "notifications_controller.get_unread_notifications.query_error",
            extra={"error": str(exc), "tenant_id": caller_organisation_id, "recipient_user_id": userId},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve unread notifications",
        ) from exc

    except Exception as exc:
        logger.exception(
            "notifications_controller.get_unread_notifications.unexpected_error",
            extra={"tenant_id": caller_organisation_id, "recipient_user_id": userId},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while retrieving unread notifications",
        ) from exc


@router.patch(
    "/notifications/{id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark notification as read",
)
async def mark_notification_read(
    id: int,
    payload: MarkNotificationReadRequest,
    caller_organisation_id: int = Depends(get_caller_organisation_id),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    """
    Mark notification as read when notification_id + tenant + recipient scope matches.
    Uses authorization-safe not-found response.
    """
    logger.info(
        "notifications_controller.mark_notification_read.start",
        extra={
            "notification_id": id,
            "tenant_id": caller_organisation_id,
            "recipient_user_id": payload.recipient_user_id,
        },
    )

    service = NotificationService(db)

    try:
        notification = await service.mark_notification_as_read(
            notification_id=id,
            tenant_id=caller_organisation_id,
            recipient_user_id=payload.recipient_user_id,
        )
        await db.commit()

        logger.info(
            "notifications_controller.mark_notification_read.success",
            extra={
                "notification_id": notification.id,
                "tenant_id": caller_organisation_id,
                "recipient_user_id": payload.recipient_user_id,
            },
        )
        return NotificationResponse.model_validate(notification)

    except ValidationServiceError as exc:
        await db.rollback()
        logger.warning(
            "notifications_controller.mark_notification_read.validation_error",
            extra={
                "error": str(exc),
                "notification_id": id,
                "tenant_id": caller_organisation_id,
                "recipient_user_id": payload.recipient_user_id,
            },
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    except NotificationNotFoundOrUnauthorizedServiceError as exc:
        await db.rollback()
        logger.info(
            "notifications_controller.mark_notification_read.not_found_or_unauthorized",
            extra={
                "notification_id": id,
                "tenant_id": caller_organisation_id,
                "recipient_user_id": payload.recipient_user_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        ) from exc

    except NotificationReadUpdateServiceError as exc:
        await db.rollback()
        logger.error(
            "notifications_controller.mark_notification_read.update_error",
            extra={
                "error": str(exc),
                "notification_id": id,
                "tenant_id": caller_organisation_id,
                "recipient_user_id": payload.recipient_user_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notification",
        ) from exc

    except Exception as exc:
        await db.rollback()
        logger.exception(
            "notifications_controller.mark_notification_read.unexpected_error",
            extra={
                "notification_id": id,
                "tenant_id": caller_organisation_id,
                "recipient_user_id": payload.recipient_user_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while updating notification",
        ) from exc
