# Architecture

TaskBridge uses a layered model -> repository -> service -> controller/route architecture.
Project, Audit, and Notification models define the persisted domain data.
Repositories contain SQLAlchemy ORM data-access operations and tenant-scoped queries.
Services enforce validation, authorization boundaries, and business rules.
FastAPI routes provide typed request and response contracts through Pydantic schemas.
Project creation, status changes, and deletion create audit records and notifications.
Audit records capture actor, organisation, entity, before/after state, timestamp, and optional actor IP.
Audit records are immutable; the service exposes no update or delete operation for audit history.
Notifications are created equally for supplied project team recipients and can be marked read by their recipient.
Tenant IDs scope repository access to prevent cross-organisation data access.
The service layer coordinates Project, Audit, and Notification writes within the same database transaction.
This design favors explicit layers and simple contracts over additional abstractions that were unnecessary for the assessment.
