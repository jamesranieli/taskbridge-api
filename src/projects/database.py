"""
Database configuration and ORM setup for TaskBridge projects module.

This module provides the SQLAlchemy declarative base for all models in the
projects package. It should be replaced or extended when the application's
main database module is created.

Future: This will be superseded by app.database.Base when the full application
is structured, allowing models to be centrally registered.
"""

from sqlalchemy.orm import declarative_base

# Create the declarative base for all ORM models in this package
Base = declarative_base()
