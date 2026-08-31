"""
Pydantic schemas for Notification & Audit API requests and responses.

Uses Pydantic v2 conventions (ConfigDict/model_config) and mirrors
validation constraints required by SPEC.md and service-layer rules.
"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_EVENT_TYPES = {"project_created", "project_status_updated", "project_deleted"}
SUPPORTED_ENTITY_TYPES = {"project"}
MAX_NOTIFICATION_MESSAGE_LENGTH = 1000


class AuditCreateRequest(BaseModel):
    """Request schema for creating an audit record (internal endpoint)."""

    tenant_id: int = Field(..., gt=0, description="Tenant/organization identifier")
    event_type: str = Field(..., min_length=1, max_length=100, description="Audit event type")
    entity_type: str = Field(..., min_length=1, max_length=100, description="Entity type")
    entity_id: int = Field(..., gt=0, description="Entity identifier")
    actor_user_id: int = Field(..., gt=0, description="Actor user identifier")
    actor_organisation_id: int = Field(..., gt=0, description="Actor organization identifier")
    previous_state: Optional[dict[str, Any]] = Field(
        None, description="State snapshot before mutation (null for create)"
    )
    new_state: Optional[dict[str, Any]] = Field(
        None, description="State snapshot after mutation (null for delete)"
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        value = v.strip()
        if value not in SUPPORTED_EVENT_TYPES:
            raise ValueError(
                "Unsupported event_type. Allowed values: "
                "project_created, project_status_updated, project_deleted"
            )
        return value

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        value = v.strip()
        if value not in SUPPORTED_ENTITY_TYPES:
            raise ValueError("Unsupported entity_type. Allowed value: project")
        return value


class AuditResponse(BaseModel):
    """Response schema for audit log records."""

    id: int
    tenant_id: int
    event_type: str
    entity_type: str
    entity_id: int
    actor_user_id: int
    actor_organisation_id: int
    previous_state: Optional[dict[str, Any]] = None
    new_state: Optional[dict[str, Any]] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditListResponse(BaseModel):
    """Response schema for audit history queries."""

    data: list[AuditResponse]
    total: int

    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    """Response schema for notification records."""

    id: int
    tenant_id: int
    recipient_user_id: int
    event_type: str
    project_id: int
    message: str
    read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """Response schema for unread notification list."""

    data: list[NotificationResponse]
    total: int

    model_config = ConfigDict(from_attributes=True)


class MarkNotificationReadRequest(BaseModel):
    """
    Request schema for marking a notification as read.

    Carries only the recipient context and desired read state.
    Tenant context comes from trusted request header.
    """

    recipient_user_id: int = Field(..., gt=0, description="Caller recipient user identifier")
    read: bool = Field(..., description="Must be true to mark as read")

    model_config = ConfigDict(extra="forbid")

    @field_validator("read")
    @classmethod
    def validate_read_true(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("read must be true")
        return v
