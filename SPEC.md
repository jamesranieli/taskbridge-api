# SPEC: Audit and Notification Functionality

## Overview

This specification defines audit logging and user notifications for the TaskBridge API. Audit records track all mutations to Projects with immutable history. Notifications alert users to significant project events within their organization.

---

## 1. Data Models

### Audit

Immutable records of all mutations to Projects.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key (auto-generated) |
| `tenant_id` | Integer | Organization ID (immutable, indexed) |
| `event_type` | String | Mutation type: `project.created`, `project.status_updated`, `project.deleted` |
| `entity_type` | String | Entity mutated: `project` (currently only type) |
| `entity_id` | Integer | Project ID (indexed) |
| `actor_user_id` | Integer | User ID who triggered the mutation |
| `actor_org_id` | Integer | Organization ID of actor (must equal `tenant_id` for isolation) |
| `before_state` | JSON | Previous state (null for create, full project dict for update/delete) |
| `after_state` | JSON | New state (full project dict, null for delete) |
| `timestamp` | DateTime | UTC timestamp of mutation (immutable) |

**Constraints:**
- Immutable after creation (no updates or deletes)
- Unique index on `(tenant_id, entity_id, timestamp)` for chronological query

### Notification

Alerts to users about project events within their organization.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key (auto-generated) |
| `tenant_id` | Integer | Organization ID (immutable, indexed) |
| `recipient_user_id` | Integer | Target user ID (indexed) |
| `event_type` | String | Event: `project.created`, `project.status_updated`, `project.deleted` |
| `project_id` | Integer | Project ID that triggered notification (indexed) |
| `message` | String | Human-readable summary (max 500 chars) |
| `read` | Boolean | Read status (default: false) |
| `created_at` | DateTime | UTC timestamp (immutable) |

---

## 2. Project Service Integration

All Project mutations must be transactional with audit and notification writes:

### create_project()
1. Insert Project (status = "active")
2. Write Audit: `event_type=project.created`, `before_state=null`, `after_state={project}`
3. Create Notifications for all team members: `"Project 'X' created"`
4. Commit transaction or rollback all

### update_status()
1. Fetch Project (current state)
2. Update Project status
3. Write Audit: `event_type=project.status_updated`, `before_state={old}`, `after_state={new}`
4. Create Notifications for all team members: `"Project 'X' status changed to archived"`
5. Commit transaction or rollback all

### delete_project()
1. Fetch Project (current state)
2. Delete Project (hard delete)
3. Write Audit: `event_type=project.deleted`, `before_state={project}`, `after_state=null`
4. Create Notifications for all team members: `"Project 'X' deleted"`
5. Commit transaction or rollback all

**Implementation:** Inject `AuditService` and `NotificationService` into `ProjectService` constructor. Call within same transaction as repository mutation.

---

## 3. API Contracts

### POST /audit
**Purpose:** Create an audit record (internal only; not exposed to client initially).

**Request:**
```json
{
  "event_type": "project.created",
  "entity_type": "project",
  "entity_id": 42,
  "actor_user_id": 10,
  "before_state": null,
  "after_state": { "id": 42, "name": "...", "status": "active" }
}
```

**Response:** `201 Created`
```json
{
  "id": "uuid",
  "tenant_id": 1,
  "timestamp": "2026-09-01T15:00:00Z"
}
```

**Authorization:** Internal service calls only. Tenant ID inferred from actor_org_id validation.
**Validation:** actor_org_id must equal tenant context.

---

### GET /audit/:projectId
**Purpose:** Retrieve audit history for a project.

**Query Parameters:**
- `event_type` (optional): Filter by event type
- `start_date` (optional): ISO 8601 start date
- `end_date` (optional): ISO 8601 end date
- `limit` (optional, default 50): Max results (1-1000)
- `offset` (optional, default 0): Pagination offset

**Response:** `200 OK`
```json
{
  "events": [
    {
      "id": "uuid",
      "event_type": "project.status_updated",
      "entity_id": 42,
      "actor_user_id": 10,
      "before_state": { "status": "active" },
      "after_state": { "status": "archived" },
      "timestamp": "2026-09-01T15:00:00Z"
    }
  ],
  "total": 5
}
```

**Authorization:** Tenant isolation enforced. User must have access to project's team or tenant-level audit permission.
**Validation:** project_id must belong to tenant. Date ranges validated (start_date ≤ end_date).

---

### GET /notifications/:userId
**Purpose:** Retrieve notifications for a user.

**Query Parameters:**
- `read` (optional): Filter by read status (`true`, `false`)
- `limit` (optional, default 50): Max results (1-1000)
- `offset` (optional, default 0): Pagination offset

**Response:** `200 OK`
```json
{
  "notifications": [
    {
      "id": "uuid",
      "event_type": "project.created",
      "project_id": 42,
      "message": "Project 'Alpha' created",
      "read": false,
      "created_at": "2026-09-01T15:00:00Z"
    }
  ],
  "total": 12
}
```

**Authorization:** User can only access own notifications. Tenant isolation enforced.
**Validation:** userId must match authenticated user or have admin privilege within tenant.

---

### PATCH /notifications/:id/read
**Purpose:** Mark a notification as read.

**Request:**
```json
{
  "read": true
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "event_type": "project.created",
  "project_id": 42,
  "read": true,
  "created_at": "2026-09-01T15:00:00Z"
}
```

**Authorization:** User can only update own notifications. Tenant isolation enforced.
**Validation:** Notification must exist and belong to authenticated user.

---

## 4. Immutability, Authorization, and Validation

**Audit Immutability:**
- No UPDATE or DELETE allowed on audit records
- Database-level constraints: no-update triggers or read-only role
- Violations return `403 Forbidden`

**Multi-Tenant Isolation:**
- All queries filtered by `tenant_id`
- Audit events from other tenants must not be accessible
- Notifications scoped to recipient_user_id within tenant_id

**Notification Authorization:**
- Users can only view/modify notifications where `recipient_user_id = authenticated_user_id` AND `tenant_id = user_tenant_id`
- Violations return `403 Forbidden` or `404 Not Found`

**Audit Filtering:**
- Supports date-range filtering: `[start_date, end_date]` (inclusive)
- Supports event-type filtering: single or comma-separated list
- Invalid date format returns `400 Bad Request`

---

## 5. Copilot vs. Human Judgment

**Copilot-Assisted:**
- Data model field definitions (audit fields, notification fields)
- Standard CRUD endpoint patterns (GET, POST, PATCH)
- Generic validation rules (date ranges, pagination limits)
- Immutability enforcement pattern

**Requires Human Judgment:**
- **Transaction scope decision**: Should audit writes occur in the same transaction as Project mutations, or asynchronously? (Spec assumes same transaction for consistency; async introduces consistency risks.)
- **Notification recipients**: Who should receive notifications for a project event? (Current spec: all team members. Alternative: configurable per event type.)
- **Audit granularity**: Should `before_state` and `after_state` contain full project snapshots or only changed fields? (Full snapshots chosen for auditability; changes field-level tracking.)
- **Notification retention**: How long should notifications persist? (Not specified; requires business decision.)
- **Role-based audit access**: Should non-admin users see full audit history or only their own actions? (Spec allows team access; further restrictions need business approval.)

---

## Out of Scope (Future)

- Audit event type `MILESTONE_REOPENED`
- Actor IP address logging
- Bulk notification deletion
- Notification email/SMS delivery
- Audit export/archive functionality
