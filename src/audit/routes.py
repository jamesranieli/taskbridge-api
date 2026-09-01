from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.schemas import AuditCreateRequest, AuditHistoryResponse, AuditResponse
from src.audit.service import AuditService
from src.database import get_db
from src.dependencies import get_tenant_id, get_user_id


router = APIRouter()


@router.post("/audit", response_model=AuditResponse)
async def create_audit(
    payload: AuditCreateRequest,
    tenant_id: int = Depends(get_tenant_id),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = AuditService(db)
    audit = await service.create_event(
        tenant_id=tenant_id,
        event_type=payload.event_type,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        actor_user_id=user_id,
        actor_org_id=tenant_id,
        before_state=payload.before_state,
        after_state=payload.after_state,
        actor_ip=payload.actor_ip,
    )
    return AuditResponse.model_validate(audit)


@router.get("/audit/{projectId}", response_model=AuditHistoryResponse)
async def get_project_audit(
    projectId: int,
    event_type: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    service = AuditService(db)
    audits, total = await service.get_project_history(
        tenant_id=tenant_id,
        project_id=projectId,
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return AuditHistoryResponse(
        items=[AuditResponse.model_validate(audit) for audit in audits],
        total=total,
    )
