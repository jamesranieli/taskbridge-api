from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    team_id: int
    name: str = Field(min_length=1)
    description: str | None = None
    recipient_user_ids: list[int]
    actor_ip: str | None = None


class ProjectUpdateRequest(BaseModel):
    team_id: int
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None


class ProjectStatusUpdateRequest(BaseModel):
    team_id: int
    new_status: str = Field(min_length=1)
    recipient_user_ids: list[int]
    actor_ip: str | None = None


class ProjectDeleteRequest(BaseModel):
    team_id: int
    recipient_user_ids: list[int]
    actor_ip: str | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    team_id: int
    name: str
    description: str | None
    status: str
