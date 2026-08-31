"""
Projects module: project management, creation, updates, and deletion.

Provides the complete project lifecycle management for TaskBridge including:
- Project creation and metadata management
- Status transitions with state-machine validation
- Multi-tenant and team-based isolation
- Soft-delete with restoration capabilities
- Pagination support for team and tenant project listings

Layered architecture:
- Model: src/projects/project.py (SQLAlchemy ORM)
- Repository: src/projects/project_repository.py (data access)
- Service: src/projects/project_service.py (business logic)
- Controller: src/projects/project_controller.py (HTTP API routes)

Package Structure:
This module includes __init__.py for conventional package structure and to ensure
reliable relative-import behavior across the projects subpackage. While modern
Python supports namespace packages without __init__.py in some scenarios, explicit
__init__.py is a standard practice for clarity and compatibility.
"""
