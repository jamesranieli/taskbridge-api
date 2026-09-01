# Scope Change Impact Analysis: MILESTONE_REOPENED Event & IP Address Capture

**Date**: 2026-09-01  
**Sprint Context**: Mid-sprint scope change for TaskBridge Notification & Audit Service  
**Scope**: Add new `MILESTONE_REOPENED` event type to audit system and capture actor IP address in all audit entries  

---

## Summary

This scope change introduces two requirements:

1. **New Event Type**: `MILESTONE_REOPENED` — a new supported event type that can be logged in the audit system
2. **IP Address Capture**: All audit entries must record the actor's IP address (source: HTTP request context)

**Impact Overview**:
- **9 affected files/modules** across models, repositories, services, schemas, and controllers
- **Change classification**: 3 additive changes, 6 breaking changes (schema and API signatures)
- **Database migration required**: Yes (add nullable `actor_ip_address` column to `audit_logs` table)
- **Backward compatibility**: Preserved for existing audit records via nullable column

---

## Affected Files & Required Changes

### 1. Data Model: `src/notifications/models.py` — `AuditLog` class

**Change Type**: BREAKING (database schema change)

**Lines Affected**: 32–114 (AuditLog class definition)

**Required Changes**:
- Add new column: `actor_ip_address = Column(String(45), nullable=True)`
  - IPv4: max 15 characters, IPv6: max 39 characters; 45-character field accommodates both
  - Nullable to preserve backward compatibility with existing audit records
  - Not indexed (to minimize storage overhead)
- Add check constraint: `CHECK(actor_ip_address IS NULL OR LENGTH(actor_ip_address) <= 45)`
- Update class docstring to document the new field
- Update `__repr__()` to exclude IP address (prevent accidental logging in debug output)

**Notes**:
- Existing audit records will have `NULL` for this column
- New audit entries will populate this field when available

---

### 2. Repository: `src/notifications/repositories.py` — `AuditRepository` class

**Change Type**: BREAKING (method signature change)

**Affected Method**: `create_audit_log()` (~line 50–80)

**Required Changes**:
- Add parameter: `actor_ip_address: Optional[str] = None`
- Pass parameter to ORM model on insertion
- No IP validation here; validation moved to service/schema layers (see below)

**Other Methods**: No changes required to query methods (`get_audit_history_by_entity()`)

**Impact**: All callers of `create_audit_log()` must supply the new parameter

---

### 3. Service: `src/notifications/services.py` — `AuditService` & event types

**Change Type**: BREAKING (method signature change) + ADDITIVE (new event type)

**Affected Method**: `create_audit_entry()` (lines 106–193)

**Required Changes**:
- Add parameter: `actor_ip_address: Optional[str] = None`
- Add validation method:
  ```python
  def _validate_actor_ip_address(ip_address: Optional[str]) -> None:
      if ip_address is None:
          return
      if not isinstance(ip_address, str) or not ip_address.strip():
          raise ValidationServiceError("actor_ip_address must be non-empty string")
      if len(ip_address) > 45:
          raise ValidationServiceError("actor_ip_address exceeds 45 characters")
  ```
- Call validation before passing to repository
- **Do not log** `actor_ip_address` in structured logging output (to prevent accidental exposure in logs)
- Pass to repository: `await self.repo.create_audit_log(..., actor_ip_address=actor_ip_address)`

**New Event Type** (line 42–46):
- Add `"milestone_reopened"` to `SUPPORTED_EVENT_TYPES` set
- Update docstring noting that this event type is now supported

**Rationale**: Service layer enforces business validation; repository layer performs data persistence

---

### 4. Service: `src/projects/project_service.py` — audit call sites

**Change Type**: BREAKING (method signatures and audit call updates)

**Affected Methods**:
- `create_project()` (lines 137–254)
- `update_status()` (lines 595–739)
- `delete_project()` (lines 743–854)

**Required Changes** (for each method):
- Add parameter: `actor_ip_address: str`
- Update existing audit service calls to include IP:
  ```python
  await audit_service.create_audit_entry(
      tenant_id=tenant_id,
      event_type="project_status_updated",
      entity_type="project",
      entity_id=project_id,
      actor_user_id=actor_user_id,
      actor_organisation_id=actor_organisation_id,
      previous_state=before_snapshot,
      new_state=after_snapshot,
      actor_ip_address=actor_ip_address,  # NEW PARAMETER
  )
  ```

**Impact**: All service method callers (primarily controller layer) must provide IP address

---

### 5. Schema: `src/notifications/schemas.py` — request/response models

**Change Type**: ADDITIVE (new optional field in request schema)

**Affected Models**: Audit log creation request schema (e.g., `AuditLogCreateRequest` or equivalent)

**Required Changes**:
- Add field: `actor_ip_address: Optional[str] = Field(None, max_length=45)`
- Add Pydantic field validator to enforce length constraint:
  ```python
  @field_validator('actor_ip_address')
  @classmethod
  def validate_ip_length(cls, v):
      if v is not None and len(v) > 45:
          raise ValueError('actor_ip_address must not exceed 45 characters')
      return v
  ```

**Backward Compatibility**: Field is optional; existing API clients need not provide it

---

### 6. Controller: `src/projects/project_controller.py` — endpoint handlers

**Change Type**: BREAKING (internal implementation; no API contract change)

**Affected Endpoints**:
- `POST /projects` (create project)
- `PATCH /projects/{id}/status` (update status)
- `DELETE /projects/{id}` (delete project)

**Required Changes** (for each endpoint):
- Extract actor IP from HTTP request context
- Add helper function:
  ```python
  def extract_actor_ip(request: Request) -> str:
      """
      Extract actor IP address from HTTP request.
      
      Uses X-Forwarded-For header if available (indicates reverse proxy).
      Falls back to direct connection IP if no proxy header found.
      Only trust X-Forwarded-For if application is configured to operate behind a trusted proxy.
      
      Returns: IP address string, or "unknown" if unable to determine
      """
      # Check for proxy header (only if behind trusted reverse proxy)
      forwarded = request.headers.get("X-Forwarded-For")
      if forwarded:
          # Take leftmost IP (original client) when multiple IPs present
          return forwarded.split(",")[0].strip()
      # Direct connection
      if request.client:
          return request.client.host
      return "unknown"
  ```
- Pass extracted IP to service method calls:
  ```python
  project = await service.create_project(
      tenant_id=tenant_id,
      team_id=team_id,
      name=name,
      description=description,
      actor_user_id=actor_user_id,
      actor_organisation_id=actor_organisation_id,
      actor_ip_address=extract_actor_ip(request),  # NEW
      recipient_user_ids=recipient_user_ids,
  )
  ```

**API Contract**: No change to request/response bodies; IP extracted server-side from request context

**Important**: Trust `X-Forwarded-For` header only if application is deployed behind a configured reverse proxy. Document this assumption.

---

### 7. Internal Controller: `src/notifications/controller.py` — POST /audit endpoint

**Change Type**: BREAKING (internal API signature change)

**Affected Endpoint**: `POST /audit` (internal endpoint for trusted services)

**Required Changes**:
- Accept `actor_ip_address` in request body as optional field
- Validate and pass to `AuditService.create_audit_entry()`
- Update internal API documentation

**Request Body Example**:
```json
{
  "tenant_id": 101,
  "event_type": "milestone_reopened",
  "entity_type": "milestone",
  "entity_id": 99,
  "actor_user_id": 9001,
  "actor_organisation_id": 101,
  "actor_ip_address": "192.168.1.100",
  "previous_state": null,
  "new_state": {"status": "reopened"}
}
```

**Backward Compatibility**: Field is optional; internal clients not providing it will default to `None`

---

### 8. Database Migration

**Change Type**: BREAKING (schema change, requires migration)

**Migration SQL**:
```sql
ALTER TABLE audit_logs
ADD COLUMN actor_ip_address VARCHAR(45) NULL;

ALTER TABLE audit_logs
ADD CONSTRAINT ck_audit_log_actor_ip_max_length
CHECK (actor_ip_address IS NULL OR LENGTH(actor_ip_address) <= 45);
```

**Backward Compatibility**:
- Column is **nullable** → existing audit records retain `NULL` for IP
- Old records remain queryable and functional
- New records will have IP populated (or explicit `None` if extraction fails)
- **Zero-downtime deployment possible**: Adding nullable column does not require exclusive locks on most database systems

---

### 9. Tests: `tests/test_project_api.py` and `tests/conftest.py`

**Change Type**: BREAKING (fixtures and test assertions require updates)

**Affected Test Files**:
- `tests/test_project_api.py` — all test cases that create, update, or delete projects
- `tests/conftest.py` — fixtures and mock setup

**Required Changes**:
- Update all calls to `ProjectService.create_project()`, `update_status()`, `delete_project()` to include `actor_ip_address` parameter
- Update fixtures in `conftest.py` to mock IP extraction (e.g., `"127.0.0.1"` for tests)
- Mock HTTP request context in integration tests to simulate IP header extraction
- Audit log assertions: expect `actor_ip_address` to be populated in new test cases
- Backward compatibility test: verify that audit query endpoints return `actor_ip_address=None` for old records

**Example Test Update**:
```python
# Before
project = await service.create_project(
    tenant_id=1,
    team_id=1,
    name="Test",
    description=None,
    actor_user_id=1,
    actor_organisation_id=1,
    recipient_user_ids=[1]
)

# After
project = await service.create_project(
    tenant_id=1,
    team_id=1,
    name="Test",
    description=None,
    actor_user_id=1,
    actor_organisation_id=1,
    actor_ip_address="127.0.0.1",  # NEW
    recipient_user_ids=[1]
)
```

---

## Security & Privacy Considerations

### IP Address Storage & Privacy

1. **Personally Identifiable Information (PII)**
   - IP addresses may be classified as PII under data protection regulations (GDPR, CCPA, etc.)
   - Audit logs with IP addresses should be retained according to the organisation's applicable privacy and compliance policies
   - No specific retention period is prescribed in this analysis; organisation must define based on regulatory and business requirements

2. **Logging Exposure**
   - **Critical**: Do not log the `actor_ip_address` field in application logs or structured logging output
   - Reason: Prevents accidental IP exposure in log aggregation systems, error traces, and debug output
   - Apply to all logging statements in service and controller layers
   - Example: When logging audit entry creation, exclude IP from the `extra` dict passed to logger

3. **X-Forwarded-For Header Trust**
   - The `X-Forwarded-For` header can be spoofed by clients if not validated by the reverse proxy
   - **Only trust this header if** the application is deployed behind a configured reverse proxy that sanitizes untrusted headers
   - Document this assumption in code and deployment configuration
   - If operating without a reverse proxy, fall back to `request.client.host` only

4. **Error Responses**
   - Never expose IP addresses in error messages returned to clients
   - Maintain generic error messages for authorization/not-found errors

---

## Summary of Changes by Classification

| Component | File | Type | Breaking? | Notes |
|-----------|------|------|-----------|-------|
| Model | `src/notifications/models.py` | Additive (column) | Yes | Nullable column; DB migration |
| Repository | `src/notifications/repositories.py` | Signature change | Yes | New parameter in create_audit_log() |
| Service | `src/notifications/services.py` | Signature change + Additive | Yes | New parameter + "milestone_reopened" event type |
| Service | `src/projects/project_service.py` | Signature change | Yes | New actor_ip_address parameter |
| Schema | `src/notifications/schemas.py` | Additive | No (optional field) | Backward compatible |
| Controller | `src/projects/project_controller.py` | Implementation change | No | No API contract change |
| Controller | `src/notifications/controller.py` | Signature change | Yes (internal) | New optional request field |
| Database | (migration) | Schema change | Yes | Nullable column, zero-downtime possible |
| Tests | `tests/test_project_api.py`, `tests/conftest.py` | Fixture updates | Yes | Must include IP in service calls |

---

## How Copilot Assisted This Analysis

### What Copilot Identified

**Prompt**: Draft an impact analysis for adding `MILESTONE_REOPENED` event type and IP address capture to audit logs without modifying source code.

**Copilot's Process**:
1. **Code Exploration**: Used file retrieval tools to systematically collect:
   - SPEC.md and REVIEW.md for architectural context
   - AuditLog, Notification, Project models
   - AuditService, NotificationService, ProjectService implementations
   - Repository layer patterns
   - Controller/route structure

2. **Data Flow Analysis**: Traced audit entry creation:
   - ProjectService methods → AuditService → AuditRepository → ORM
   - Identified all callers and affected signatures

3. **Schema Analysis**: Reviewed AuditLog model to determine:
   - Appropriate data type for IP (VARCHAR(45))
   - Existing constraints and patterns
   - Nullable vs. non-null field strategy
   - Check constraint syntax

4. **Pattern Recognition**: Identified consistent patterns:
   - Service layer validation approach
   - Repository layer data persistence
   - Schema-based request validation (Pydantic)
   - HTTP request context extraction in controllers

### What Human Review Corrected

**Assumptions Removed by Human Feedback**:

1. **Fictional Components**
   - ❌ Removed: Hypothetical Milestone model and `reopen_milestone()` method
   - ✓ Corrected: `MILESTONE_REOPENED` is simply a new event type name supported by existing architecture; no new entity required

2. **Over-Scoped Requirements**
   - ❌ Removed: Retention cleanup job, DBA review process, multi-day implementation schedule, legal workflow, compliance rating
   - ✓ Corrected: Noted that retention policy is organisational decision; scope limited to architecture changes

3. **Implementation Details**
   - ❌ Removed: Arbitrary 90-day retention period, Alembic migration examples, deployment runbook
   - ✓ Corrected: Generic migration pattern; retention policy left to organisation

4. **Logging Guidance**
   - ❌ Removed: Suggestion to include IP in audit service logs
   - ✓ Corrected: Explicitly stated IP must be **excluded** from application logs to prevent accidental exposure

5. **Validation Placement**
   - ❌ Removed: Repository-layer IP validation
   - ✓ Corrected: Validation belongs in service and schema layers, consistent with existing patterns

6. **Unsupported Assumptions**
   - ❌ Removed: Arbitrary "HIGH" compliance risk rating
   - ✓ Corrected: Noted privacy considerations without prescribing regulatory interpretation

7. **Scope Boundaries**
   - ❌ Removed: Test file paths that don't exist in repository
   - ✓ Corrected: Listed only actual existing test files (tests/test_project_api.py, tests/conftest.py)

**Key Learning**: Initial AI-generated analysis focused on completeness and exhaustiveness; human judgment re-calibrated scope to match the 120-minute practitioner assessment constraint and removed speculative requirements not supported by the original case study.

