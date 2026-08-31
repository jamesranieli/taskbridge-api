"""
Project model for TaskBridge multi-tenant project management.

This module defines the SQLAlchemy ORM model for projects, which represent
work items managed within teams and organizations (tenants).

Design Principles:
- Multi-tenant isolation enforced at application level (tenant_id, team_id)
- Soft deletes preserve audit history (is_deleted flag)
- Timestamps auto-managed by ORM (onupdate for updated_at)
- Immutable fields: id, tenant_id, team_id, created_at, is_deleted
- Status field supports service-layer validation (not enforced at DB level)

LIMITATION - Referential Integrity Pending Team/Tenant Integration:
- tenant_id and team_id are stored as plain integer columns (no FK constraints)
- Database-level referential integrity is NOT enforced until Tenant/Team models exist
- Application-layer isolation (repository/service) enforces tenant+team filtering
- When Tenant and Team models are implemented, add ForeignKey constraints to this model
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, CheckConstraint

from .database import Base


class Project(Base):
    """
    Project model representing a project within a tenant and team.
    
    Multi-tenant isolation is enforced at the application layer via
    repository and service filtering on tenant_id and team_id.
    
    Uses soft deletes (is_deleted flag) to preserve historical data and audit trails.
    
    Attributes:
        id (int): Unique project identifier (immutable, auto-generated)
        tenant_id (int): Tenant (organization) ID this project belongs to (immutable)
                        Stored as plain integer; future FK to tenants.id when model exists
        team_id (int): Team ID within tenant that owns this project (immutable)
                      Stored as plain integer; future FK to teams.id when model exists
        name (str): Human-readable project name (255 chars max, required)
        description (Optional[str]): Long-form project description (optional)
        status (str): Project lifecycle status (active, archived, inactive)
                     Valid transitions enforced at service layer, not database
        created_at (datetime): UTC timestamp when project was created (immutable, auto-set)
        updated_at (datetime): UTC timestamp of last modification (auto-managed by ORM)
        is_deleted (bool): Soft delete flag (immutable after set to True)
    
    Future Integration:
        When Tenant and Team models are added to the application, update this model to:
        - Add ForeignKey constraints: ForeignKey("tenants.id"), ForeignKey("teams.id")
        - Add ORM relationships with back_populates for navigation
        - Leverage database-level referential integrity
    """
    
    __tablename__ = "projects"
    
    # Valid status values - must match service layer constants
    VALID_STATUSES = {"active", "archived", "inactive"}
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Multi-tenant isolation (indexed integer columns, no FK until Tenant/Team models exist)
    tenant_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Organization/tenant this project belongs to (future: FK to tenants.id)",
    )
    team_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Team within the tenant that owns this project (future: FK to teams.id)",
    )
    
    # Project metadata
    name = Column(String(255), nullable=False, index=True, comment="Project name")
    description = Column(Text, nullable=True, comment="Project description")
    
    # Status management (transitions enforced by service layer, not DB)
    status = Column(
        String(50),
        default="active",
        nullable=False,
        index=True,
        comment="Project lifecycle status: active, archived, or inactive",
    )
    
    # Timestamps (auto-managed by ORM via onupdate)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC timestamp when project was created",
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC timestamp of last modification (auto-managed)",
    )
    
    # Soft delete flag (immutable after set)
    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Soft delete flag; preserves audit history",
    )
    
    # Database-level constraints to support data integrity
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'inactive')",
            name="ck_project_status_valid",
        ),
        CheckConstraint(
            "tenant_id > 0",
            name="ck_project_tenant_id_positive",
        ),
        CheckConstraint(
            "team_id > 0",
            name="ck_project_team_id_positive",
        ),
    )
    
    def __repr__(self) -> str:
        """String representation for debugging and logging."""
        return (
            f"<Project(id={self.id}, tenant_id={self.tenant_id}, team_id={self.team_id}, "
            f"name={self.name!r}, status={self.status}, is_deleted={self.is_deleted})>"
        )
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        status_marker = " [DELETED]" if self.is_deleted else ""
        return f"Project '{self.name}' (ID: {self.id}, Status: {self.status}){status_marker}"
