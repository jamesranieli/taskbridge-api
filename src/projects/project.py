from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class Project(Base):
    """Project model representing a project within a tenant."""
    
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active", nullable=False)  # active, archived, inactive
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    tenant = relationship("Tenant", back_populates="projects")
    team = relationship("Team", back_populates="projects")
    audit_logs = relationship("AuditLog", back_populates="project")
    
    def __repr__(self):
        return f"<Project(id={self.id}, tenant_id={self.tenant_id}, team_id={self.team_id}, name={self.name}, status={self.status})>"
