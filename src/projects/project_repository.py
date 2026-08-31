from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models import Project


class ProjectRepository:
    """Repository for Project model with tenant and team isolation."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, tenant_id: int, team_id: int, name: str, description: str = None, status: str = "active") -> Project:
        """Create a new project."""
        project = Project(
            tenant_id=tenant_id,
            team_id=team_id,
            name=name,
            description=description,
            status=status
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project
    
    async def read_by_id(self, tenant_id: int, project_id: int) -> Project | None:
        """Read a project by ID with tenant isolation."""
        result = await self.db.execute(
            select(Project).where(
                and_(
                    Project.id == project_id,
                    Project.tenant_id == tenant_id,
                    Project.is_deleted == False
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def read_by_id_and_team(self, tenant_id: int, team_id: int, project_id: int) -> Project | None:
        """Read a project by ID with tenant and team isolation."""
        result = await self.db.execute(
            select(Project).where(
                and_(
                    Project.id == project_id,
                    Project.tenant_id == tenant_id,
                    Project.team_id == team_id,
                    Project.is_deleted == False
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def list_by_tenant(self, tenant_id: int) -> list[Project]:
        """List all projects for a tenant."""
        result = await self.db.execute(
            select(Project).where(
                and_(
                    Project.tenant_id == tenant_id,
                    Project.is_deleted == False
                )
            )
        )
        return result.scalars().all()
    
    async def list_by_team(self, tenant_id: int, team_id: int) -> list[Project]:
        """List all projects for a specific team within a tenant."""
        result = await self.db.execute(
            select(Project).where(
                and_(
                    Project.tenant_id == tenant_id,
                    Project.team_id == team_id,
                    Project.is_deleted == False
                )
            )
        )
        return result.scalars().all()
    
    async def update(self, tenant_id: int, project_id: int, **kwargs) -> Project | None:
        """Update a project by ID."""
        project = await self.read_by_id(tenant_id, project_id)
        if not project:
            return None
        
        for key, value in kwargs.items():
            if hasattr(project, key) and key not in ["id", "tenant_id", "created_at", "is_deleted"]:
                setattr(project, key, value)
        
        project.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(project)
        return project
    
    async def delete(self, tenant_id: int, project_id: int) -> bool:
        """Soft delete a project."""
        project = await self.read_by_id(tenant_id, project_id)
        if not project:
            return False
        
        project.is_deleted = True
        project.updated_at = datetime.utcnow()
        await self.db.commit()
        return True
    
    async def restore(self, tenant_id: int, project_id: int) -> Project | None:
        """Restore a soft-deleted project."""
        result = await self.db.execute(
            select(Project).where(
                and_(
                    Project.id == project_id,
                    Project.tenant_id == tenant_id,
                    Project.is_deleted == True
                )
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            return None
        
        project.is_deleted = False
        project.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(project)
        return project
