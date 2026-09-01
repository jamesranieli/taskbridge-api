from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.dependencies import enforce_user_match, get_tenant_id, get_user_id
from src.notifications.schemas import (
    NotificationListResponse,
    NotificationReadResponse,
    NotificationResponse,
)
from src.notifications.service import NotificationService


router = APIRouter()


@router.get("/notifications/{userId}", response_model=NotificationListResponse)
async def get_user_notifications(
    userId: int,
    read: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tenant_id: int = Depends(get_tenant_id),
    authenticated_user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    enforce_user_match(authenticated_user_id, userId)

    service = NotificationService(db)
    notifications, total = await service.get_user_notifications(
        tenant_id=tenant_id,
        recipient_user_id=userId,
        read=read,
        limit=limit,
        offset=offset,
    )

    return NotificationListResponse(
        items=[
            NotificationResponse.model_validate(notification)
            for notification in notifications
        ],
        total=total,
    )


@router.patch(
    "/notifications/{id}/read",
    response_model=NotificationReadResponse,
)
async def mark_notification_read(
    id: str,
    tenant_id: int = Depends(get_tenant_id),
    authenticated_user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    notification = await service.mark_notification_read(
        tenant_id=tenant_id,
        recipient_user_id=authenticated_user_id,
        notification_id=id,
    )

    return NotificationReadResponse.model_validate(notification)
