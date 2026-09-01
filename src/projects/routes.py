from fastapi import APIRouter, Body, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.dependencies import get_tenant_id, get_user_id
from src.projects.project_service import ProjectService
from src.projects.schemas import (
    ProjectCreateRequest,
    ProjectDeleteRequest,
    ProjectResponse,
    ProjectStatusUpdateRequest,
    ProjectUpdateRequest,
)


router = APIRouter(prefix="/projects")


@router.post("", response_model=ProjectResponse)
async def create_project(
    payload: ProjectCreateRequest,
    tenant_id: int = Depends(get_tenant_id),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.create_project(
        tenant_id=tenant_id,
        team_id=payload.team_id,
        name=payload.name,
        actor_user_id=user_id,
        recipient_user_ids=payload.recipient_user_ids,
        description=payload.description,
        actor_ip=payload.actor_ip,
    )
    return ProjectResponse.model_validate(project)


@router.get("/{projectId}", response_model=ProjectResponse)
async def get_project(
    projectId: int,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.get_project(
        tenant_id=tenant_id,
        project_id=projectId,
    )
    return ProjectResponse.model_validate(project)


@router.put("/{projectId}", response_model=ProjectResponse)
async def update_project(
    projectId: int,
    payload: ProjectUpdateRequest,
    tenant_id: int = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.update_project(
        tenant_id=tenant_id,
        team_id=payload.team_id,
        project_id=projectId,
        name=payload.name,
        description=payload.description,
    )
    return ProjectResponse.model_validate(project)


@router.patch("/{projectId}/status", response_model=ProjectResponse)
async def update_status(
    projectId: int,
    payload: ProjectStatusUpdateRequest,
    tenant_id: int = Depends(get_tenant_id),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.update_status(
        tenant_id=tenant_id,
        team_id=payload.team_id,
        project_id=projectId,
        new_status=payload.new_status,
        actor_user_id=user_id,
        recipient_user_ids=payload.recipient_user_ids,
        actor_ip=payload.actor_ip,
    )
    return ProjectResponse.model_validate(project)


@router.delete("/{projectId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    projectId: int,
    payload: ProjectDeleteRequest = Body(...),
    tenant_id: int = Depends(get_tenant_id),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    await service.delete_project(
        tenant_id=tenant_id,
        team_id=payload.team_id,
        project_id=projectId,
        actor_user_id=user_id,
        recipient_user_ids=payload.recipient_user_ids,
        actor_ip=payload.actor_ip,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
