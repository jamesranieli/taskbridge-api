"""
Notification model for TaskBridge user alerts.

Tracks user notifications for project events within organizations.
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime

from src.projects.project import Base


class Notification(Base):
    """
    Notification record for user project event alerts.
    
    Attributes:
        id (str): UUID primary key
        tenant_id (int): Tenant (organization) ID for isolation (immutable)
        recipient_user_id (int): Target user ID (indexed)
        event_type (str): Event type (project.created, project.status_updated, project.deleted)
        project_id (int): Project ID that triggered notification (indexed)
        message (str): Human-readable summary (max 500 chars)
        read (bool): Read status (default: false)
        created_at (datetime): UTC timestamp when notification was created (immutable)
    """
    
    __tablename__ = "notifications"
    
    # Primary key
    id = Column(String(36), primary_key=True, index=True)  # UUID
    
    # Multi-tenant isolation
    tenant_id = Column(Integer, nullable=False, index=True)
    
    # Recipient and event targeting
    recipient_user_id = Column(Integer, nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    project_id = Column(Integer, nullable=False, index=True)
    
    # Message and read status
    message = Column(String(500), nullable=False)
    read = Column(Boolean, default=False, nullable=False)
    
    # Timestamp (immutable)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"<Notification(id={self.id}, tenant_id={self.tenant_id}, recipient_user_id={self.recipient_user_id}, project_id={self.project_id}, read={self.read})>"
