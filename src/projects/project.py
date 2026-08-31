"""
Project model for TaskBridge multi-tenant project management.

This module defines the SQLAlchemy ORM model for projects, which represent
work items managed within teams and organizations (tenants).

Design Principles:
- Multi-tenant isolation enforced at model and database levels (tenant_id, team_id)
- Soft deletes preserve audit history (is_deleted flag)
- Timestamps auto-managed by ORM (onupdate for updated_at)
- Immutable fields: id, tenant_id, team_id, created_at, is_deleted
- Status field supports service-layer validation (not enforced at DB level)
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, CheckConstraint

from .database import Base


class Project(Base):
    """
    Project model representing a project within a tenant and team.
    
    Multi-tenant isolation is enforced via tenant_id and team_id foreign keys.
    Uses soft deletes (is_deleted flag) to preserve historical data and audit trails.
    
    Attributes:
        id (int): Unique project identifier (immutable, auto-generated)
        tenant_id (int): Tenant (organization) ID this project belongs to (immutable)
        team_id (int): Team ID within tenant that owns this project (immutable)
        name (str): Human-readable project name (255 chars max, required)
        description (Optional[str]): Long-form project description (optional)
        status (str): Project lifecycle status (active, archived, inactive)
            Valid transitions enforced at service layer, not database
        created_at (datetime): UTC timestamp when project was created (immutable, auto-set)
        updated_at (datetime): UTC timestamp of last modification (auto-managed by ORM)
        is_deleted (bool): Soft delete flag (immutable after set to True)
    
    Relationships (configured when Tenant and Team models are available):
        tenant: Refers to Tenant model (back_populates="projects")
        team: Refers to Team model (back_populates="projects")
    
    Note:
        Relationships with Tenant and Team are currently commented out pending
        availability of those models. Uncomment and configure foreign_keys when ready.
    """
    
    __tablename__ = "projects"
    
    # Valid status values - must match service layer constants
    VALID_STATUSES = {"active", "archived", "inactive"}
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Multi-tenant isolation (immutable foreign keys)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
        comment="Organization/tenant this project belongs to"
    )
    team_id = Column(
        Integer,
        ForeignKey("teams.id"),
        nullable=False,
        index=True,
        comment="Team within the tenant that owns this project"
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
        comment="Project lifecycle status: active, archived, or inactive"
    )
    
    # Timestamps (auto-managed by ORM via onupdate)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC timestamp when project was created"
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="UTC timestamp of last modification (auto-managed)"
    )
    
    # Soft delete flag (immutable after set)
    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Soft delete flag; preserves audit history"
    )
    
    # Database-level constraints to support data integrity
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'inactive')",
            name="ck_project_status_valid"
        ),
        CheckConstraint(
            "tenant_id > 0",
            name="ck_project_tenant_id_positive"
        ),
        CheckConstraint(
            "team_id > 0",
            name="ck_project_team_id_positive"
        ),
    )
    
    # Relationships (uncomment and configure when Tenant and Team models are available)
    # tenant = relationship("Tenant", back_populates="projects", foreign_keys=[tenant_id])
    # team = relationship("Team", back_populates="projects", foreign_keys=[team_id])
    
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
