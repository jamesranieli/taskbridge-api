"""
Notification and Audit models for TaskBridge multi-tenant event tracking.

This module defines SQLAlchemy ORM models for:
- AuditLog: append-only audit events for project lifecycle changes
- Notification: unread/read notification records per recipient user

Design principles:
- Multi-tenant isolation via tenant_id on all records
- No foreign keys to tenant/team/user tables that do not yet exist in this repository
- UTC timestamps generated server-side by ORM defaults
- Audit records are modeled as append-only; update/delete prevention is enforced
  in repository/service layers when those layers are implemented
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    JSON,
    Index,
)

from src.projects.database import Base


class AuditLog(Base):
    """
    Append-only audit record for entity lifecycle events.

    Fields align with SPEC.md:
    - id
    - tenant_id
    - event_type
    - entity_type
    - entity_id
    - actor_user_id
    - actor_organisation_id
    - previous_state
    - new_state
    - timestamp
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Multi-tenant isolation
    tenant_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Organization/tenant identifier (no FK until tenant model exists)",
    )

    # Event metadata
    event_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Event type (e.g., project_created, project_status_updated, project_deleted)",
    )
    entity_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Entity type (e.g., project)",
    )
    entity_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Target entity identifier",
    )

    # Actor context
    actor_user_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="User ID that triggered the event",
    )
    actor_organisation_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Organisation context of actor (no FK until org model exists)",
    )

    # State snapshots (before/after)
    previous_state = Column(
        JSON,
        nullable=True,
        comment="JSON snapshot before mutation; null for create",
    )
    new_state = Column(
        JSON,
        nullable=True,
        comment="JSON snapshot after mutation; null for delete",
    )

    # Server-generated UTC timestamp
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC timestamp generated at audit record creation",
    )

    __table_args__ = (
        CheckConstraint("tenant_id > 0", name="ck_audit_log_tenant_id_positive"),
        CheckConstraint("entity_id > 0", name="ck_audit_log_entity_id_positive"),
        CheckConstraint("actor_user_id > 0", name="ck_audit_log_actor_user_id_positive"),
        CheckConstraint(
            "actor_organisation_id > 0",
            name="ck_audit_log_actor_organisation_id_positive",
        ),
        CheckConstraint("length(trim(event_type)) > 0", name="ck_audit_log_event_type_nonempty"),
        CheckConstraint("length(trim(entity_type)) > 0", name="ck_audit_log_entity_type_nonempty"),
        Index(
            "ix_audit_logs_tenant_entity_timestamp",
            "tenant_id",
            "entity_type",
            "entity_id",
            "timestamp",
        ),
        Index("ix_audit_logs_tenant_event_timestamp", "tenant_id", "event_type", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, tenant_id={self.tenant_id}, event_type={self.event_type!r}, "
            f"entity_type={self.entity_type!r}, entity_id={self.entity_id})>"
        )


class Notification(Base):
    """
    Notification record for unread/read project-related events.

    Fields align with SPEC.md:
    - id
    - tenant_id
    - recipient_user_id
    - event_type
    - project_id
    - message
    - read
    - created_at
    """

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)

    # Multi-tenant isolation and recipient
    tenant_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Organization/tenant identifier (no FK until tenant model exists)",
    )
    recipient_user_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Recipient user identifier (no FK until user model exists)",
    )

    # Event context
    event_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Notification event type",
    )
    project_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Related project identifier",
    )

    # Payload
    message = Column(
        String(1000),
        nullable=False,
        comment="Notification message text (bounded length)",
    )
    read = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Read status (false = unread, true = read)",
    )

    # Server-generated UTC timestamp
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC timestamp generated at notification creation",
    )

    __table_args__ = (
        CheckConstraint("tenant_id > 0", name="ck_notification_tenant_id_positive"),
        CheckConstraint(
            "recipient_user_id > 0",
            name="ck_notification_recipient_user_id_positive",
        ),
        CheckConstraint("project_id > 0", name="ck_notification_project_id_positive"),
        CheckConstraint(
            "length(trim(event_type)) > 0",
            name="ck_notification_event_type_nonempty",
        ),
        CheckConstraint("length(trim(message)) > 0", name="ck_notification_message_nonempty"),
        CheckConstraint(
            "length(message) <= 1000",
            name="ck_notification_message_max_length",
        ),
        Index(
            "ix_notifications_tenant_recipient_read_created",
            "tenant_id",
            "recipient_user_id",
            "read",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, tenant_id={self.tenant_id}, recipient_user_id={self.recipient_user_id}, "
            f"event_type={self.event_type!r}, project_id={self.project_id}, read={self.read})>"
        )
