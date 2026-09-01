from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: int
    recipient_user_id: int
    event_type: str
    project_id: int
    message: str
    read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int


class NotificationReadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    read: bool
