"""Tests for Notification and Audit service integration."""

from datetime import datetime, timedelta, timezone

import pytest


def mutation_headers(
    tenant_id: int,
    recipients: str = "101,102,103",
    actor_user_id: int = 1001,
) -> dict[str, str]:
    """Build trusted mutation context headers."""
    return {
        "X-Organisation-ID": str(tenant_id),
        "X-Actor-User-ID": str(actor_user_id),
        "X-Recipient-User-Ids": recipients,
    }


def organisation_headers(tenant_id: int) -> dict[str, str]:
    """Build trusted organisation context header."""
    return {
        "X-Organisation-ID": str(tenant_id),
    }


async def create_project(test_client, tenant_id: int = 1) -> dict:
    """Create a project and return its response payload."""
    response = await test_client.post(
        f"/api/v1/tenants/{tenant_id}/teams/5/projects",
        json={
            "name": "Audit Test Project",
            "description": "Project used for notification and audit testing",
        },
        headers=mutation_headers(tenant_id),
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_equal_notification_dispatch_on_project_state_change(test_client):
    """All supplied team recipients receive the same status-change notification."""
    project = await create_project(test_client)

    response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project['id']}/status",
        json={"status": "archived"},
        headers=mutation_headers(1),
    )
    assert response.status_code == 200

    matching_notifications = []

    for user_id in (101, 102, 103):
        notifications_response = await test_client.get(
            f"/notifications/{user_id}",
            headers=organisation_headers(1),
        )
        assert notifications_response.status_code == 200

        matching = [
            item
            for item in notifications_response.json()["data"]
            if item["project_id"] == project["id"]
            and item["event_type"] == "project_status_updated"
        ]

        assert len(matching) == 1
        matching_notifications.append(matching[0])

    assert len(matching_notifications) == 3
    assert len({item["message"] for item in matching_notifications}) == 1


@pytest.mark.asyncio
async def test_audit_entry_created_on_project_milestone_update(test_client):
    """Project status update creates the required immutable audit event."""
    project = await create_project(test_client)

    update_response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project['id']}/status",
        json={"status": "archived"},
        headers=mutation_headers(1),
    )
    assert update_response.status_code == 200

    audit_response = await test_client.get(
        f"/audit/{project['id']}",
        headers=organisation_headers(1),
    )
    assert audit_response.status_code == 200

    matching = [
        item
        for item in audit_response.json()["data"]
        if item["event_type"] == "project_status_updated"
    ]

    assert len(matching) == 1
    audit = matching[0]
    assert audit["entity_type"] == "project"
    assert audit["entity_id"] == project["id"]
    assert audit["actor_user_id"] == 1001
    assert audit["actor_organisation_id"] == 1
    assert audit["previous_state"]["status"] == "active"
    assert audit["new_state"]["status"] == "archived"


@pytest.mark.asyncio
async def test_audit_entry_cannot_be_deleted_or_overwritten(test_client):
    """Audit history exposes no update/delete operation and remains unchanged."""
    project = await create_project(test_client)

    before_response = await test_client.get(
        f"/audit/{project['id']}",
        headers=organisation_headers(1),
    )
    assert before_response.status_code == 200
    before = before_response.json()

    overwrite_response = await test_client.patch(
        f"/audit/{project['id']}",
        json={"event_type": "project_deleted"},
        headers=organisation_headers(1),
    )
    assert overwrite_response.status_code == 405

    delete_response = await test_client.delete(
        f"/audit/{project['id']}",
        headers=organisation_headers(1),
    )
    assert delete_response.status_code == 405

    after_response = await test_client.get(
        f"/audit/{project['id']}",
        headers=organisation_headers(1),
    )
    assert after_response.status_code == 200
    assert after_response.json() == before


@pytest.mark.asyncio
async def test_audit_history_date_range_filter(test_client):
    """Audit history can be restricted to a requested UTC date range."""
    project = await create_project(test_client)

    before_update = datetime.now(timezone.utc)

    update_response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project['id']}/status",
        json={"status": "archived"},
        headers=mutation_headers(1),
    )
    assert update_response.status_code == 200

    after_update = datetime.now(timezone.utc)

    response = await test_client.get(
        f"/audit/{project['id']}",
        params={
            "from": before_update.isoformat(),
            "to": after_update.isoformat(),
        },
        headers=organisation_headers(1),
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data) >= 1
    parsed_timestamps = []
    for item in data:
        timestamp = datetime.fromisoformat(item["timestamp"])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        parsed_timestamps.append(timestamp)

    assert all(
        before_update <= timestamp <= after_update
        for timestamp in parsed_timestamps
    )


@pytest.mark.asyncio
async def test_audit_history_event_type_filter(test_client):
    """Audit history can be filtered by event type."""
    project = await create_project(test_client)

    update_response = await test_client.patch(
        f"/api/v1/tenants/1/teams/5/projects/{project['id']}/status",
        json={"status": "archived"},
        headers=mutation_headers(1),
    )
    assert update_response.status_code == 200

    response = await test_client.get(
        f"/audit/{project['id']}",
        params={"eventType": "project_status_updated"},
        headers=organisation_headers(1),
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data) == 1
    assert data[0]["event_type"] == "project_status_updated"
    assert data[0]["entity_id"] == project["id"]


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_access_another_organisation_audit_log(
    test_client,
):
    """Another organisation cannot retrieve a project's audit history."""
    project = await create_project(test_client, tenant_id=1)

    response = await test_client.get(
        f"/audit/{project['id']}",
        headers=organisation_headers(2),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["data"] == []


@pytest.mark.asyncio
async def test_create_audit_endpoint_success(test_client):
    """Trusted caller can create an audit entry directly."""
    payload = {
        "tenant_id": 1,
        "event_type": "project_created",
        "entity_type": "project",
        "entity_id": 999,
        "actor_user_id": 1001,
        "actor_organisation_id": 1,
        "previous_state": None,
        "new_state": {"status": "active"},
    }

    response = await test_client.post(
        "/audit",
        json=payload,
        headers=organisation_headers(1),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["tenant_id"] == 1
    assert data["event_type"] == "project_created"
    assert data["entity_id"] == 999
    assert data["actor_user_id"] == 1001


@pytest.mark.asyncio
async def test_create_audit_rejects_organisation_mismatch(test_client):
    """Audit creation is forbidden when payload tenant does not match caller."""
    payload = {
        "tenant_id": 1,
        "event_type": "project_created",
        "entity_type": "project",
        "entity_id": 999,
        "actor_user_id": 1001,
        "actor_organisation_id": 1,
        "previous_state": None,
        "new_state": {"status": "active"},
    }

    response = await test_client.post(
        "/audit",
        json=payload,
        headers=organisation_headers(2),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_organisation_header_rejected(test_client):
    """Organisation header must be a positive integer."""
    response = await test_client.get(
        "/notifications/101",
        headers=organisation_headers(0),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unread_notifications_and_mark_read_flow(test_client):
    """Unread notification can be retrieved, marked read, then disappears."""
    project = await create_project(test_client)

    notifications_response = await test_client.get(
        "/notifications/101",
        headers=organisation_headers(1),
    )
    assert notifications_response.status_code == 200

    notifications = notifications_response.json()["data"]
    assert len(notifications) >= 1

    notification = next(
        item for item in notifications if item["project_id"] == project["id"]
    )
    assert notification["read"] is False

    mark_response = await test_client.patch(
        f"/notifications/{notification['id']}/read",
        json={
            "recipient_user_id": 101,
            "read": True,
        },
        headers=organisation_headers(1),
    )

    assert mark_response.status_code == 200
    assert mark_response.json()["read"] is True

    after_response = await test_client.get(
        "/notifications/101",
        headers=organisation_headers(1),
    )
    assert after_response.status_code == 200

    after_ids = {
        item["id"]
        for item in after_response.json()["data"]
    }
    assert notification["id"] not in after_ids


@pytest.mark.asyncio
async def test_mark_notification_read_wrong_recipient_returns_404(test_client):
    """A different recipient cannot mark another user's notification as read."""
    project = await create_project(test_client)

    notifications_response = await test_client.get(
        "/notifications/101",
        headers=organisation_headers(1),
    )
    notification = next(
        item
        for item in notifications_response.json()["data"]
        if item["project_id"] == project["id"]
    )

    response = await test_client.patch(
        f"/notifications/{notification['id']}/read",
        json={
            "recipient_user_id": 999,
            "read": True,
        },
        headers=organisation_headers(1),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mark_notification_read_false_rejected(test_client):
    """Mark-read request requires read=true."""
    response = await test_client.patch(
        "/notifications/999/read",
        json={
            "recipient_user_id": 101,
            "read": False,
        },
        headers=organisation_headers(1),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_audit_event_filter_rejected(test_client):
    """Unsupported audit event filters are rejected."""
    response = await test_client.get(
        "/audit/1",
        params={"eventType": "not_a_real_event"},
        headers=organisation_headers(1),
    )

    assert response.status_code == 422
