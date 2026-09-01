"""
Project model for TaskBridge multi-tenant project management.

Defines the SQLAlchemy ORM model for projects representing work items
managed within teams and organizations (tenants).
"""

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Project(Base):
    """
    Project model representing a project within a tenant and team.
    
    Attributes:
        id (int): Unique project identifier (auto-generated primary key)
        tenant_id (int): Tenant (organization) ID this project belongs to
        team_id (int): Team ID within tenant that owns this project
        name (str): Human-readable project name (max 255 chars)
        description (str): Optional long-form project description
        status (str): Project lifecycle status (active, archived, inactive)
    """
    
    __tablename__ = "projects"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Multi-tenant isolation
    tenant_id = Column(Integer, nullable=False, index=True)
    team_id = Column(Integer, nullable=False, index=True)
    
    # Project metadata
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Status management
    status = Column(String(50), default="active", nullable=False, index=True)
    
    def __repr__(self) -> str:
        """String representation for debugging and logging."""
        return f"<Project(id={self.id}, tenant_id={self.tenant_id}, team_id={self.team_id}, name={self.name!r}, status={self.status})>"
