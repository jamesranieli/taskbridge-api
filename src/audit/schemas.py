from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditCreateRequest(BaseModel):
    event_type: str
    entity_type: str
    entity_id: int
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    actor_ip: str | None = None


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: int
    event_type: str
    entity_type: str
    entity_id: int
    actor_user_id: int
    actor_org_id: int
    actor_ip: str | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    timestamp: datetime


class AuditHistoryResponse(BaseModel):
    items: list[AuditResponse]
    total: int
