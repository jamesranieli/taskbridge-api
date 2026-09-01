"""
Integration tests for Project API endpoints.

Tests cover create, list, update, delete, pagination, isolation, validation, and error handling.
All tests use isolated in-memory SQLite test database.
Production database .data/projects.db is not affected by test execution.

Tests have NOT been executed yet. All assertions are proposed.
"""

import pytest


def mutation_headers(tenant_id: int, recipients: str = "101,102") -> dict[str, str]:
    """Build required trusted-context headers for Project mutation endpoints."""
    return {
        "X-Organisation-ID": str(tenant_id),
        "X-Actor-User-ID": "1001",
        "X-Recipient-User-Ids": recipients,
    }


# ==================== CREATE PROJECT TESTS ====================

@pytest.mark.asyncio
async def test_create_project_success(test_client, valid_project_create):
    """Test successful project creation with valid input."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["tenant_id"] == 1
    assert data["team_id"] == 5
    assert data["name"] == "Test Project"
    assert data["description"] == "A test project"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_project_minimal(test_client, valid_project_minimal):
    """Test project creation without description."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_minimal,
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Minimal Project"
    assert data["description"] is None


@pytest.mark.asyncio
async def test_create_project_empty_name(test_client):
    """Test project creation with empty name raises 422."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={"name": "   "},
        headers=mutation_headers(1)
    )
    
    # Pydantic validates via min_length=1 and custom validator
    # FastAPI returns 422 for validation errors (not 400)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_project_name_too_long(test_client):
    """Test project creation with name > 255 chars raises 422."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={"name": "x" * 256},
        headers=mutation_headers(1)
    )
    
    # Pydantic validates max_length=255
    # FastAPI returns 422 for validation errors
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_project_description_too_long(test_client):
    """Test project creation with description > 10000 chars raises 422."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={"name": "Valid", "description": "x" * 10001},
        headers=mutation_headers(1)
    )
    
    # Pydantic validates max_length=10000
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_project_name_whitespace_stripped(test_client):
    """Test that project name whitespace is stripped during validation."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={"name": "  Test Project  ", "description": "  Test  "},
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 201
    data = response.json()
    # Pydantic validators strip whitespace
    assert data["name"] == "Test Project"
    assert data["description"] == "Test"


@pytest.mark.asyncio
async def test_create_project_missing_name(test_client):
    """Test project creation without required name field raises 422."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={},
        headers=mutation_headers(1)
    )
    
    # Pydantic requires 'name' field (...)
    assert response.status_code == 422


# ==================== LIST PROJECTS BY TEAM TESTS ====================

@pytest.mark.asyncio
async def test_list_projects_empty_team(test_client):
    """Test listing projects for team with no projects."""
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["data"] == []
    assert data["limit"] == 20
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_list_projects_multiple_projects(test_client, valid_project_create):
    """Test listing multiple projects for a team."""
    # Create 3 projects
    project_ids = []
    for i in range(3):
        create_data = valid_project_create.copy()
        create_data["name"] = f"Project {i}"
        resp = await test_client.post(
            "/api/v1/tenants/1/teams/5/projects",
            json=create_data,
            headers=mutation_headers(1)
        )
        project_ids.append(resp.json()["id"])
    
    # List projects
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["data"]) == 3


@pytest.mark.asyncio
async def test_list_projects_pagination_limit(test_client, valid_project_create):
    """Test pagination with custom limit parameter."""
    # Create 5 projects
    for i in range(5):
        create_data = valid_project_create.copy()
        create_data["name"] = f"Project {i}"
        await test_client.post(
            "/api/v1/tenants/1/teams/5/projects",
            json=create_data,
            headers=mutation_headers(1)
        )
    
    # Request with limit=2
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects?limit=2"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2
    assert data["limit"] == 2
    assert data["total"] == 5


@pytest.mark.asyncio
async def test_list_projects_pagination_offset(test_client, valid_project_create):
    """Test pagination with offset parameter."""
    # Create 5 projects
    created_ids = []
    for i in range(5):
        create_data = valid_project_create.copy()
        create_data["name"] = f"Project {i}"
        resp = await test_client.post(
            "/api/v1/tenants/1/teams/5/projects",
            json=create_data,
            headers=mutation_headers(1)
        )
        created_ids.append(resp.json()["id"])
    
    # Request first page
    response1 = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects?limit=2&offset=0"
    )
    first_page = response1.json()["data"]
    
    # Request second page
    response2 = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects?limit=2&offset=2"
    )
    second_page = response2.json()["data"]
    
    assert len(first_page) == 2
    assert len(second_page) == 2
    # Pages should have different projects
    assert first_page[0]["id"] != second_page[0]["id"]


@pytest.mark.asyncio
async def test_list_projects_invalid_limit_too_small(test_client):
    """Test that limit < 1 raises 422."""
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects?limit=0"
    )
    
    # FastAPI Query validator ge=1
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_invalid_limit_too_large(test_client):
    """Test that limit > 1000 raises 422."""
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects?limit=1001"
    )
    
    # FastAPI Query validator le=1000
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_invalid_offset_negative(test_client):
    """Test that negative offset raises 422."""
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects?offset=-1"
    )
    
    # FastAPI Query validator ge=0
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_projects_excludes_deleted(test_client, valid_project_create):
    """Test that soft-deleted projects are excluded from listing."""
    # Create 2 projects
    resp1 = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={**valid_project_create, "name": "Project 1"},
        headers=mutation_headers(1)
    )
    project1_id = resp1.json()["id"]
    
    resp2 = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json={**valid_project_create, "name": "Project 2"},
        headers=mutation_headers(1)
    )
    
    # Delete first project
    await test_client.delete(
        f"/api/v1/tenants/1/teams/5/projects/{project1_id}",
        headers=mutation_headers(1)
    )
    
    # List projects
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["name"] == "Project 2"


# ==================== UPDATE STATUS TESTS ====================

@pytest.mark.asyncio
async def test_update_status_active_to_archived(test_client, valid_project_create):
    """Test valid status transition: active -> archived."""
    # Create project (starts in active)
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    # Update status to archived
    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "archived"},
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "archived"


@pytest.mark.asyncio
async def test_update_status_active_to_inactive(test_client, valid_project_create):
    """Test valid status transition: active -> inactive."""
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "inactive"},
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"


@pytest.mark.asyncio
async def test_update_status_archived_to_active(test_client, valid_project_create):
    """Test valid status transition: archived -> active."""
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    # Archive
    await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "archived"},
        headers=mutation_headers(1)
    )
    
    # Reactivate
    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "active"},
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_update_status_invalid_status_value(test_client, valid_project_create):
    """Test updating with invalid status value raises 422."""
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    # Try invalid status
    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "invalid"},
        headers=mutation_headers(1)
    )
    
    # Pydantic schema validates status in {active, archived, inactive}
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_status_invalid_transition(test_client, valid_project_create):
    """Test invalid state transition raises 400."""
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    # Archive it
    await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "archived"},
        headers=mutation_headers(1)
    )
    
    # Try invalid transition (archived -> inactive not allowed)
    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}/status",
        json={"status": "inactive"},
        headers=mutation_headers(1)
    )
    
    # Service layer raises InvalidProjectStatusError -> 400
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_status_nonexistent_project(test_client):
    """Test updating status on nonexistent project raises 403."""
    response = await test_client.patch(
        "/api/v1/tenants/1/teams/5/projects/99999/status",
        json={"status": "archived"},
        headers=mutation_headers(1)
    )
    
    # Service raises ProjectNotFoundError -> 403 (not 404 to avoid leaking info)
    assert response.status_code == 403


# ==================== DELETE PROJECT TESTS ====================

@pytest.mark.asyncio
async def test_delete_project_success(test_client, valid_project_create):
    """Test successful project soft delete."""
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    response = await test_client.delete(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}",
        headers=mutation_headers(1)
    )
    
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_project_nonexistent(test_client):
    """Test deleting nonexistent project raises 403."""
    response = await test_client.delete(
        "/api/v1/tenants/1/teams/5/projects/99999",
        headers=mutation_headers(1)
    )
    
    # Service raises ProjectNotFoundError -> 403
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_deleted_project_hidden_from_list(test_client, valid_project_create):
    """Test that deleted project is hidden from list operations."""
    create_resp = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = create_resp.json()["id"]
    
    # Delete it
    await test_client.delete(
        f"/api/v1/tenants/1/teams/5/projects/{project_id}",
        headers=mutation_headers(1)
    )
    
    # List should show 0 projects
    response = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    
    assert response.json()["total"] == 0


# ==================== TENANT ISOLATION TESTS ====================

@pytest.mark.asyncio
async def test_tenant_isolation_list(test_client, valid_project_create):
    """Test that listing is isolated by tenant."""
    # Create 2 projects in tenant 1
    for i in range(2):
        await test_client.post(
            "/api/v1/tenants/1/teams/5/projects",
            json={**valid_project_create, "name": f"T1 Project {i}"},
            headers=mutation_headers(1)
        )
    
    # Create 1 project in tenant 2
    await test_client.post(
        "/api/v1/tenants/2/teams/5/projects",
        json={**valid_project_create, "name": "T2 Project"},
        headers=mutation_headers(2)
    )
    
    # List tenant 1 projects
    response1 = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    
    # List tenant 2 projects
    response2 = await test_client.get(
        "/api/v1/tenants/2/teams/5/projects"
    )
    
    assert response1.json()["total"] == 2
    assert response2.json()["total"] == 1
    assert response2.json()["data"][0]["name"] == "T2 Project"


@pytest.mark.asyncio
async def test_tenant_isolation_update_status(test_client, valid_project_create):
    """Test that update is isolated by tenant."""
    # Create project in tenant 1, team 5
    resp1 = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = resp1.json()["id"]
    
    # Try to update from tenant 2, team 5 (wrong tenant)
    response = await test_client.patch(
        f"/api/v1/tenants/2/teams/5/projects/{project_id}/status",
        json={"status": "archived"},
        headers=mutation_headers(2)
    )
    
    # Service cannot find project in tenant 2 -> 403
    assert response.status_code == 403
    
    # Original project in tenant 1 should still be active
    resp_check = await test_client.get(
        f"/api/v1/tenants/1/teams/5/projects?offset=0"
    )
    assert resp_check.json()["data"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_tenant_isolation_delete(test_client, valid_project_create):
    """Test that delete is isolated by tenant."""
    # Create project in tenant 1, team 5
    resp1 = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = resp1.json()["id"]
    
    # Try to delete from tenant 2, team 5 (wrong tenant)
    response = await test_client.delete(
        f"/api/v1/tenants/2/teams/5/projects/{project_id}",
        headers=mutation_headers(2)
    )
    
    # Cannot find in tenant 2 -> 403
    assert response.status_code == 403
    
    # Project should still be visible in tenant 1
    resp_check = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    assert resp_check.json()["total"] == 1


# ==================== TEAM ISOLATION TESTS ====================

@pytest.mark.asyncio
async def test_team_isolation_list(test_client, valid_project_create):
    """Test that listing is isolated by team."""
    # Create 2 projects in team 5
    for i in range(2):
        await test_client.post(
            "/api/v1/tenants/1/teams/5/projects",
            json={**valid_project_create, "name": f"Team5 Project {i}"},
            headers=mutation_headers(1)
        )
    
    # Create 1 project in team 10
    await test_client.post(
        "/api/v1/tenants/1/teams/10/projects",
        json={**valid_project_create, "name": "Team10 Project"},
        headers=mutation_headers(1)
    )
    
    # List team 5 projects
    response1 = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    
    # List team 10 projects
    response2 = await test_client.get(
        "/api/v1/tenants/1/teams/10/projects"
    )
    
    assert response1.json()["total"] == 2
    assert response2.json()["total"] == 1


@pytest.mark.asyncio
async def test_team_isolation_update_status(test_client, valid_project_create):
    """Test that update is isolated by team."""
    # Create project in team 5
    resp1 = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = resp1.json()["id"]
    
    # Try to update from team 10 (wrong team)
    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/10/projects/{project_id}/status",
        json={"status": "archived"},
        headers=mutation_headers(1)
    )
    
    # Cannot find in team 10 -> 403
    assert response.status_code == 403
    
    # Project should still be in team 5, active
    resp_check = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    assert resp_check.json()["data"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_team_isolation_delete(test_client, valid_project_create):
    """Test that delete is isolated by team."""
    # Create project in team 5
    resp1 = await test_client.post(
        "/api/v1/tenants/1/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    project_id = resp1.json()["id"]
    
    # Try to delete from team 10 (wrong team)
    response = await test_client.delete(
        f"/api/v1/tenants/1/teams/10/projects/{project_id}",
        headers=mutation_headers(1)
    )
    
    # Cannot find in team 10 -> 403
    assert response.status_code == 403
    
    # Project should still exist in team 5
    resp_check = await test_client.get(
        "/api/v1/tenants/1/teams/5/projects"
    )
    assert resp_check.json()["total"] == 1


# ==================== INVALID ID TESTS ====================

@pytest.mark.asyncio
async def test_invalid_tenant_id_zero(test_client, valid_project_create):
    """Test that tenant_id=0 is rejected by FastAPI path validation."""
    response = await test_client.post(
        "/api/v1/tenants/0/teams/5/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    
    # FastAPI Path validator: gt=0
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_team_id_zero(test_client, valid_project_create):
    """Test that team_id=0 is rejected by FastAPI path validation."""
    response = await test_client.post(
        "/api/v1/tenants/1/teams/0/projects",
        json=valid_project_create,
        headers=mutation_headers(1)
    )
    
    # FastAPI Path validator: gt=0
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_project_id_zero(test_client):
    """Test that project_id=0 is rejected by FastAPI path validation."""
    response = await test_client.delete(
        "/api/v1/tenants/1/teams/5/projects/0",
        headers=mutation_headers(1)
    )
    
    # FastAPI Path validator: gt=0
    assert response.status_code == 422


# ==================== SERVICE LAYER ERROR BEHAVIOR TESTS ====================
# These tests verify that the service layer validates inputs and enforces business rules.
# They do NOT test database transaction rollback after a database failure.

@pytest.mark.asyncio
async def test_service_validation_empty_name(test_db_session):
    """Test that service validates empty project name."""
    from src.projects.project_service import ProjectService
    
    service = ProjectService(test_db_session)
    
    # Try to create with empty name (after strip)
    with pytest.raises(ValueError, match="cannot be empty"):
        await service.create_project(
            tenant_id=1,
            team_id=5,
            name="   ",
            description="Test",
            actor_user_id=1001,
            actor_organisation_id=1,
            recipient_user_ids=[101, 102],
        )


@pytest.mark.asyncio
async def test_service_validation_invalid_transition(test_db_session):
    """Test that service validates status transitions per state machine."""
    from src.projects.project_service import ProjectService, InvalidProjectStatusError
    
    service = ProjectService(test_db_session)
    
    # Create project
    project = await service.create_project(
        tenant_id=1,
        team_id=5,
        name="Test",
        description="Test",
        actor_user_id=1001,
        actor_organisation_id=1,
        recipient_user_ids=[101, 102],
    )
    
    # Archive it
    await service.update_status(
        1, 5, project.id, "archived",
        actor_user_id=1001,
        actor_organisation_id=1,
        recipient_user_ids=[101, 102],
    )
    
    # Try invalid transition (archived -> inactive)
    with pytest.raises(InvalidProjectStatusError):
        await service.update_status(
            1, 5, project.id, "inactive",
            actor_user_id=1001,
            actor_organisation_id=1,
            recipient_user_ids=[101, 102],
        )
