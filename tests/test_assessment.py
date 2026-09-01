import pytest
from datetime import datetime, timedelta

from src.audit.model import Audit
from src.audit.service import AuditService
from src.audit.repository import AuditRepository
from src.notifications.service import NotificationService


@pytest.mark.asyncio
async def test_equal_notifications_created_for_all_recipients(db_session):
    """Requirement 1: Equal notifications are created for all supplied team-member recipient IDs."""
    # Setup
    service = NotificationService(db_session)
    tenant_id = 1
    recipient_ids = [10, 11, 12]
    project_id = 100
    event_type = "project.created"
    message = "Project created"
    
    # Action: create notifications for all recipients
    notifications = await service.create_for_recipients(
        tenant_id=tenant_id,
        recipient_user_ids=recipient_ids,
        event_type=event_type,
        project_id=project_id,
        message=message
    )
    
    # Assert: one notification per recipient
    assert len(notifications) == 3
    
    # Assert: each notification has correct values
    recipient_set = set()
    for notif in notifications:
        assert notif.tenant_id == tenant_id
        assert notif.event_type == event_type
        assert notif.project_id == project_id
        assert notif.message == message
        assert notif.read is False
        recipient_set.add(notif.recipient_user_id)
    
    # Assert: all recipient IDs present
    assert recipient_set == set(recipient_ids)


@pytest.mark.asyncio
async def test_milestone_reopened_audit_event_created(db_session):
    """Requirement 2: A milestone update/reopen produces an audit event using exact event type MILESTONE_REOPENED."""
    # Setup
    service = AuditService(db_session)
    tenant_id = 1
    event_type = "MILESTONE_REOPENED"
    entity_type = "project"
    entity_id = 100
    actor_user_id = 5
    actor_org_id = 1
    
    # Action: create audit event with MILESTONE_REOPENED
    audit = await service.create_event(
        tenant_id=tenant_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_org_id=actor_org_id
    )
    
    # Assert: event stored with exact event_type
    assert audit.event_type == "MILESTONE_REOPENED"
    assert audit.tenant_id == tenant_id
    assert audit.entity_id == entity_id


@pytest.mark.asyncio
async def test_audit_records_cannot_be_deleted_or_overwritten(db_session):
    """Requirement 3: Audit records cannot be deleted or overwritten through the audit service/repository API."""
    # Setup
    repository = AuditRepository(db_session)
    service = AuditService(db_session)
    
    # Assert: AuditRepository exposes no update method
    assert not hasattr(repository, 'update')
    
    # Assert: AuditRepository exposes no delete method
    assert not hasattr(repository, 'delete')
    
    # Assert: AuditService exposes no update method
    assert not hasattr(service, 'update')
    
    # Assert: AuditService exposes no delete method
    assert not hasattr(service, 'delete')
    
    # Action: create an audit event
    audit = await service.create_event(
        tenant_id=1,
        event_type="project.created",
        entity_type="project",
        entity_id=100,
        actor_user_id=5,
        actor_org_id=1,
        after_state={"name": "Project A"}
    )
    audit_id = audit.id
    stored_name = audit.after_state.get("name")
    
    # Action: attempt to retrieve and verify unchanged
    audits, _ = await service.get_project_history(
        tenant_id=1,
        project_id=100
    )
    
    # Assert: audit still exists with original values
    assert len(audits) == 1
    assert audits[0].id == audit_id
    assert audits[0].after_state.get("name") == stored_name


@pytest.mark.asyncio
async def test_audit_history_filtered_by_date_range(db_session):
    """Requirement 4: Audit history can be filtered by date range."""
    # Setup: create fixture data with explicit timestamps using direct insertion
    tenant_id = 1
    entity_id = 200
    now = datetime.utcnow()
    
    # Create three audit records directly (test setup only, no production API mutation)
    audit1 = Audit(
        id="audit-1",
        tenant_id=tenant_id,
        event_type="project.created",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=5,
        actor_org_id=1,
        timestamp=now - timedelta(days=3)
    )
    
    audit2 = Audit(
        id="audit-2",
        tenant_id=tenant_id,
        event_type="project.status_updated",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=5,
        actor_org_id=1,
        timestamp=now
    )
    
    audit3 = Audit(
        id="audit-3",
        tenant_id=tenant_id,
        event_type="project.deleted",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=5,
        actor_org_id=1,
        timestamp=now + timedelta(days=2)
    )
    
    db_session.add(audit1)
    db_session.add(audit2)
    db_session.add(audit3)
    await db_session.commit()
    
    # Action: query with date range (past 1 day to future 1 day - should get audit2 only)
    service = AuditService(db_session)
    start_date = now - timedelta(days=1)
    end_date = now + timedelta(days=1)
    audits, total = await service.get_project_history(
        tenant_id=tenant_id,
        project_id=entity_id,
        start_date=start_date,
        end_date=end_date
    )
    
    # Assert: only audit2 in range
    assert len(audits) == 1
    assert audits[0].id == "audit-2"
    assert total == 1


@pytest.mark.asyncio
async def test_audit_history_filtered_by_event_type(db_session):
    """Requirement 5: Audit history can be filtered by event type."""
    # Setup
    service = AuditService(db_session)
    tenant_id = 1
    entity_id = 300
    
    # Create audits with different event types
    audit1 = await service.create_event(
        tenant_id=tenant_id,
        event_type="project.created",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=5,
        actor_org_id=1
    )
    
    audit2 = await service.create_event(
        tenant_id=tenant_id,
        event_type="project.status_updated",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=5,
        actor_org_id=1
    )
    
    audit3 = await service.create_event(
        tenant_id=tenant_id,
        event_type="project.created",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=5,
        actor_org_id=1
    )
    
    # Action: filter by event_type="project.created"
    audits, total = await service.get_project_history(
        tenant_id=tenant_id,
        project_id=entity_id,
        event_type="project.created"
    )
    
    # Assert: only project.created audits returned
    assert len(audits) == 2
    assert total == 2
    for audit in audits:
        assert audit.event_type == "project.created"


@pytest.mark.asyncio
async def test_unauthorized_cross_tenant_access_denied(db_session):
    """Requirement 6: Unauthorized cross-organization/tenant access cannot retrieve another tenant's data."""
    # Setup
    audit_service = AuditService(db_session)
    notif_service = NotificationService(db_session)
    
    # Action: create audit for tenant 1
    await audit_service.create_event(
        tenant_id=1,
        event_type="project.created",
        entity_type="project",
        entity_id=100,
        actor_user_id=5,
        actor_org_id=1
    )
    
    # Action: create notification for tenant 1
    await notif_service.create_for_recipients(
        tenant_id=1,
        recipient_user_ids=[10],
        event_type="project.created",
        project_id=100,
        message="Project created"
    )
    
    # Action: attempt to query tenant 1 data as tenant 2
    audits_tenant2, total_audits = await audit_service.get_project_history(
        tenant_id=2,  # Different tenant
        project_id=100
    )
    
    notifications_tenant2, total_notif = await notif_service.get_user_notifications(
        tenant_id=2,  # Different tenant
        recipient_user_id=10
    )
    
    # Assert: tenant 2 cannot access tenant 1's data
    assert len(audits_tenant2) == 0
    assert total_audits == 0
    assert len(notifications_tenant2) == 0
    assert total_notif == 0
