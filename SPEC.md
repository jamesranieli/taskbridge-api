# SPEC: TaskBridge Notification & Audit Service

## Purpose and Scope

The Notification & Audit Service extends the existing Project Service by recording immutable audit events for project lifecycle changes and producing user-facing notifications for relevant team members.  
Scope for this spec is limited to: data models, HTTP API contracts, integration points from Project operations, validation/authorization/error rules, and architecture alignment with the current repository patterns.

Out of scope: UI concerns, asynchronous delivery channels (email/push), cross-repo event bus design, and any implementation code in this phase.

## Required Layered Architecture

The required service layering is:

**model → repository → service → controller/route**

Responsibilities:
- **model**: persistence entities and database schema mapping.
- **repository**: data access and query/filter operations.
- **service**: business rules (tenant checks, immutability enforcement, snapshot construction, notification orchestration).
- **controller/route**: HTTP request parsing, validation binding, and response/status shaping.

Inbound request flow remains HTTP-first (request enters controller/route), but business and persistence execution must still follow the required layering above.

## Data Models

### AuditLog
| Field | Type | Notes |
|---|---|---|
| `id` | `int` | System-generated primary key |
| `tenant_id` (organisation identifier) | `int` | Required tenant boundary key |
| `event_type` | `str` | Project event category (validated enum-like string) |
| `entity_type` | `str` | Resource type, e.g. `"project"` |
| `entity_id` | `int` | Target entity identifier (project id) |
| `actor_user_id` | `int` | User performing action |
| `actor_organisation_id` | `int` | Organisation context of actor |
| `previous_state` snapshot | `dict \| None` (JSON object) | State before mutation; `null` on create |
| `new_state` snapshot | `dict \| None` (JSON object) | State after mutation; `null` on delete |
| `timestamp` | `datetime` (UTC) | **Server-generated** event creation timestamp (immutable) |

### Notification
| Field | Type | Notes |
|---|---|---|
| `id` | `int` | System-generated primary key |
| `tenant_id` (organisation identifier) | `int` | Required tenant boundary key |
| `recipient_user_id` | `int` | Destination user |
| `event_type` | `str` | Event category associated with notification |
| `project_id` | `int` | Related project identifier |
| `message` | `str` | Human-readable message |
| `read` status | `bool` | `false` by default; set `true` when read |
| `created_at` timestamp | `datetime` (UTC) | Notification creation time |

## API Contracts

### 1) `POST /audit` (internal endpoint)
Create an immutable audit log record.

This endpoint is **internal**, intended to be called by the Project Service (or trusted internal services), not as a general public client endpoint. It requires trusted service/authorization context and must still enforce tenant isolation.

**Request body**
```json
{
  "tenant_id": 101,
  "event_type": "project_status_updated",
  "entity_type": "project",
  "entity_id": 55,
  "actor_user_id": 9001,
  "actor_organisation_id": 101,
  "previous_state": {"status": "active"},
  "new_state": {"status": "archived"}
}
```

**Response (201 Created)**
```json
{
  "id": 321,
  "tenant_id": 101,
  "event_type": "project_status_updated",
  "entity_type": "project",
  "entity_id": 55,
  "actor_user_id": 9001,
  "actor_organisation_id": 101,
  "previous_state": {"status": "active"},
  "new_state": {"status": "archived"},
  "timestamp": "2026-08-31T20:15:00Z"
}
```

---

### 2) `GET /audit/{projectId}`
List audit entries for a project with optional filters.

**Path parameter**
- `projectId` (`int`, required)

**Query parameters (optional)**
- `from` (`datetime`, inclusive lower bound, UTC)
- `to` (`datetime`, inclusive upper bound, UTC)
- `eventType` (`str`)

**Response (200 OK)**
```json
{
  "data": [
    {
      "id": 321,
      "tenant_id": 101,
      "event_type": "project_status_updated",
      "entity_type": "project",
      "entity_id": 55,
      "actor_user_id": 9001,
      "actor_organisation_id": 101,
      "previous_state": {"status": "active"},
      "new_state": {"status": "archived"},
      "timestamp": "2026-08-31T20:15:00Z"
    }
  ],
  "total": 1
}
```

---

### 3) `GET /notifications/{userId}`
Return unread notifications for a user (tenant-scoped).

**Path parameter**
- `userId` (`int`, required)

**Response (200 OK)**
```json
{
  "data": [
    {
      "id": 888,
      "tenant_id": 101,
      "recipient_user_id": 9002,
      "event_type": "project_created",
      "project_id": 55,
      "message": "Project \"Alpha\" was created.",
      "read": false,
      "created_at": "2026-08-31T20:16:00Z"
    }
  ],
  "total": 1
}
```

---

### 4) `PATCH /notifications/{id}/read`
Mark a notification as read.

**Path parameter**
- `id` (`int`, required)

**Request body**
```json
{
  "read": true
}
```

**Response (200 OK)**
```json
{
  "id": 888,
  "tenant_id": 101,
  "recipient_user_id": 9002,
  "event_type": "project_created",
  "project_id": 55,
  "message": "Project \"Alpha\" was created.",
  "read": true,
  "created_at": "2026-08-31T20:16:00Z"
}
```

## Integration with Existing Project Service

Integrate with existing remediated Project Service flows:

1. **On project create**
   - Audit: create one `project_created` entry with:
     - `previous_state = null`
     - `new_state = created project snapshot`
   - Notifications: create unread notifications for all relevant team members.

2. **On project status update**
   - Audit: create one `project_status_updated` entry with:
     - `previous_state = snapshot before update`
     - `new_state = snapshot after update`
   - Notifications: create unread notifications for all relevant team members.

3. **On project delete**
   - Audit: create one `project_deleted` entry with:
     - `previous_state = snapshot before delete`
     - `new_state = null`
   - Notifications: create unread notifications for all relevant team members.

Audit entry creation must capture before/after state as applicable and must not alter existing Project API contracts.

### Notification Fan-out Integration Boundary

The requirement is to create notifications for all relevant team members.  
The current repository does not include a Team/User membership persistence model to resolve team recipients locally. Therefore, recipient resolution is an explicit integration boundary/assumption:
- Notification service expects resolved recipient user IDs from an upstream trusted source **or**
- Notification service integrates with an external/team membership provider.
- This spec does not define or invent new team-membership tables/models inside the current repository.

## Multi-Tenant Authorization and Isolation Rules

- Every AuditLog and Notification record must be tenant-bound via `tenant_id`.
- Requests can only access records where caller tenant context equals record `tenant_id`.
- `GET /audit/{projectId}` must verify project belongs to caller tenant.
- `GET /notifications/{userId}` must only return unread notifications where both tenant and user are authorized.
- `PATCH /notifications/{id}/read` must reject cross-tenant or wrong-recipient updates.
- Internal `POST /audit` must enforce tenant isolation even with trusted service context.
- Never leak record existence across tenants (use consistent not-found/forbidden strategy per existing API conventions).

## Audit Immutability Rules

- Audit records are append-only.
- No update or delete endpoints for audit entities.
- `POST /audit` is the only write operation for audit logs.
- Audit `timestamp` is server-generated at creation and immutable thereafter.
- Repository/service logic must prevent mutation after creation.

## Validation Rules

- **IDs** (`id`, `tenant_id`, `entity_id`, `project_id`, `actor_user_id`, `actor_organisation_id`, `recipient_user_id`): required positive integers where applicable.
- **`event_type`**: required non-empty string; allowed values constrained to supported project events (`project_created`, `project_status_updated`, `project_deleted`) unless explicitly extended.
- **Dates/timestamps** (`timestamp`, `from`, `to`, `created_at`): valid ISO-8601 UTC datetimes.
- **Date filter logic**: if both `from` and `to` are provided, enforce `from <= to`.
- **State snapshots** (`previous_state`, `new_state`): object-or-null JSON snapshots; must serialize deterministic project state fields used by current service contracts.
- **Notification `message`**: required non-empty trimmed string, bounded length (consistent with existing schema style that enforces max lengths and trimming).
- **POST /audit timestamp rule**: client must not supply `timestamp`; server assigns it.

## Error Handling Expectations

- `400 Bad Request`: malformed payload, invalid query params, invalid date range, invalid event type.
- `404 Not Found`: project/notification not found within tenant scope.
- `403 Forbidden` (or existing equivalent policy): authenticated but not authorized for tenant/user/resource.
- `409 Conflict`: invalid state transition scenarios if surfaced by underlying project lifecycle rules.
- `422 Unprocessable Entity`: schema validation failure (FastAPI/Pydantic behavior).
- `500 Internal Server Error`: unexpected failures with sanitized response body and logged context.
- Error payloads should remain consistent with current Project Service response conventions.

## Copilot Assistance and Human Judgment

**Copilot-assisted drafting**
- Initial structure of this SPEC, endpoint catalog, and first-pass data model/validation wording were drafted with Copilot support.
- Formatting of request/response contract examples and alignment to repository layering style were accelerated by Copilot.

**Human judgment, validation, and correction required**
- Confirming execution-reality findings (e.g., 35 tests collected vs previously claimed 42, `python -m pytest` import behavior, and 50% coverage) required actual human-run verification.
- Security-sensitive multi-tenant authorization and isolation decisions require human review and approval.
- Final event taxonomy, team-member notification policy, and immutability enforcement strategy must be validated by maintainers against product and compliance requirements.
- Any potential divergence between generated assumptions and real runtime behavior must be resolved by human testing before implementation.
