"""
Audit model for TaskBridge immutable event logging.

Tracks all mutations to Projects with immutable records.
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, JSON, DateTime

from src.projects.project import Base


class Audit(Base):
    """
    Immutable audit record tracking Project mutations.
    
    Attributes:
        id (str): UUID primary key
        tenant_id (int): Tenant (organization) ID for isolation
        event_type (str): Mutation type (project.created, project.status_updated, project.deleted, MILESTONE_REOPENED)
        entity_type (str): Entity mutated (currently: project)
        entity_id (int): Project ID that was mutated (indexed)
        actor_user_id (int): User ID who triggered the mutation
        actor_org_id (int): Organization ID of actor (must equal tenant_id)
        actor_ip (str): Optional IP address of actor (nullable)
        before_state (dict): Previous state (null for create, full project dict for update/delete)
        after_state (dict): New state (full project dict, null for delete)
        timestamp (datetime): UTC timestamp of mutation (immutable, indexed)
    """
    
    __tablename__ = "audits"
    
    # Primary key
    id = Column(String(36), primary_key=True, index=True)  # UUID
    
    # Multi-tenant isolation
    tenant_id = Column(Integer, nullable=False, index=True)
    
    # Event tracking
    event_type = Column(String(50), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False, index=True)
    
    # Actor information
    actor_user_id = Column(Integer, nullable=False)
    actor_org_id = Column(Integer, nullable=False)
    actor_ip = Column(String(45), nullable=True)
    
    # State snapshots (JSON for flexibility)
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    
    # Timestamp (immutable)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"<Audit(id={self.id}, tenant_id={self.tenant_id}, event_type={self.event_type}, entity_id={self.entity_id}, timestamp={self.timestamp})>"
