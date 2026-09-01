# TaskBridge API

TaskBridge is a small FastAPI service demonstrating Project, Audit, and Notification workflows with tenant-scoped data access.

## Architecture

The implementation follows:

`model -> repository -> service -> controller/route`

SQLAlchemy ORM is used for persistence, Pydantic models define typed API contracts, and business rules are enforced in the service layer.

## Requirements

- Python 3.12+
- FastAPI
- SQLAlchemy
- aiosqlite
- Pydantic
- pytest
- pytest-asyncio

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the API

Start the FastAPI application with:

```bash
uvicorn src.main:app --reload
```

Interactive API documentation is available at:

- `/docs`
- `/redoc`

## Identity Headers

Requests that require tenant or user identity use:

- `X-Tenant-ID`
- `X-User-ID`

Both values must be positive integers.

## Project Endpoints

- `POST /projects`
- `GET /projects/{projectId}`
- `PUT /projects/{projectId}`
- `PATCH /projects/{projectId}/status`
- `DELETE /projects/{projectId}`

## Audit Endpoints

- `POST /audit`
- `GET /audit/{projectId}`

Audit history supports optional event-type, date-range, limit, and offset filters.

## Notification Endpoints

- `GET /notifications/{userId}`
- `PATCH /notifications/{id}/read`

Notification access is scoped to the authenticated user and tenant.

## Testing

Run the six required assessment tests:

```bash
pytest tests/test_assessment.py -v
```

The current implementation passes all six required tests.

## Assessment Documentation

- `SPEC.md`
- `REVIEW.md`
- `IMPACT_ANALYSIS.md`
- `PROMPTS.md`
- `TOOL_STRATEGY.md`
- `ARCHITECTURE.md`
- `PR_DESCRIPTION.md`

Repository-wide Copilot guidance is stored in:

- `.github/copilot-instructions.md`
