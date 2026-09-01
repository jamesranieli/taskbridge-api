"""
Custom exceptions for project service layer.
"""


class ServiceError(Exception):
    """Base exception for all service-layer errors."""
    pass


class ProjectNotFoundError(ServiceError):
    """Raised when a project cannot be found or accessed."""
    pass


class InvalidProjectStatusError(ServiceError):
    """Raised when a project status transition is invalid."""
    pass


class ProjectValidationError(ServiceError):
    """Raised when project input validation fails."""
    pass
