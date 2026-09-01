# TaskBridge Copilot Instructions

- Use Python, FastAPI, SQLAlchemy, Pydantic, and pytest.
- Follow model -> repository -> service -> controller/route layering.
- Use SQLAlchemy ORM only; no raw SQL.
- Enforce validation and business rules in the service layer.
- Keep all data tenant-scoped using organisation/tenant IDs.
- Use typed request and response schemas.
- Use specific exceptions and structured logging.
- Audit records are immutable: never update or delete them.
- Keep implementations simple and limited to assessment requirements.
