# Pull Request Description

## Summary

This change remediates the inherited Project Service and adds Audit and Notification functionality using a layered model -> repository -> service -> controller/route architecture. Project create, status update, and delete operations now produce immutable audit history and notifications for supplied team recipients. The implementation also includes tenant isolation, typed API contracts, filtering, actor IP support for the mid-sprint scope change, and the six required assessment tests.

## AI Tool Disclosure

GitHub Copilot was used throughout the assessment for initial generation, code-change proposals, review, debugging assistance, test generation, and implementation suggestions. Repository instructions and written specifications were used to constrain generation.

Estimated contribution by final implementation and documentation:
- AI-assisted/generated starting material: approximately 65%
- Human-authored, corrected, reviewed, or materially revised work: approximately 35%

These percentages are estimates because many generated changes were subsequently corrected or constrained through human review.

## Integration and Contracts

Project, Audit, and Notification use a shared SQLAlchemy declarative Base and asynchronous SQLAlchemy sessions. Repositories provide ORM-only, tenant-scoped persistence. Services enforce business rules and coordinate cross-service behavior. FastAPI routes expose typed Pydantic request and response contracts.

Project creation, status changes, and deletion coordinate Project persistence with Audit and Notification writes. Audit history supports event-type and date-range filters. Notification retrieval is tenant- and recipient-scoped, and read state can only be changed through the Notification service.

## Testing and Known Gaps

The six assessment-required tests pass:
- Equal notifications are created for all supplied recipients.
- A `MILESTONE_REOPENED` audit event is created.
- Audit records cannot be deleted or overwritten through the service contract.
- Audit history can be filtered by date range.
- Audit history can be filtered by event type.
- Unauthorized cross-tenant access is denied.

The FastAPI application also imports successfully and registers the expected Project, Audit, and Notification routes.

Known gaps: the assessment implementation does not include production authentication, database migrations, deployment infrastructure, or production observability. Identity is represented through minimal request-header dependencies because full authentication infrastructure was outside the requested scope.

## Risk / Tradeoff

Recipient user IDs are supplied to Project operations rather than resolved through a separate Team membership service. This keeps the implementation within the assessment scope and allows equal notification behavior to be tested, but a production system should derive recipients from authoritative membership data.

Actor IP is stored only when supplied and is intentionally excluded from validation error messages and structured logging. This reduces unnecessary exposure, but production retention and access policies would still need to be defined.

## Self-Review Checklist

- [x] Followed model -> repository -> service -> controller/route layering.
- [x] Used SQLAlchemy ORM rather than raw SQL.
- [x] Added typed request and response contracts.
- [x] Enforced tenant-scoped repository access.
- [x] Kept audit records immutable through the service API.
- [x] Added the required Audit and Notification endpoints.
- [x] Completed impact analysis before implementing the scope change.
- [x] Added exactly the six required assessment tests.
- [x] Ran all six required tests successfully.
- [x] Verified FastAPI route registration.
- [x] Reviewed generated code rather than accepting Copilot output solely on completion claims.

## Peer Review Simulation

1. **ProjectService recipient validation:** Validate that every `recipient_user_id` belongs to the project's tenant/team before creating notifications. The current assessment contract accepts supplied recipient IDs, which is sufficient for the exercise but would be an authorization risk if exposed unchanged in production.

2. **Audit actor IP retention:** Define a retention and access policy for `actor_ip` before production deployment. The implementation avoids logging the raw value, but persisted IP addresses still require explicit privacy and retention decisions.

3. **API exception mapping:** Add centralized FastAPI exception handlers that translate domain-specific service exceptions into consistent HTTP 4xx responses. The service layer uses specific exceptions, but production API consumers would benefit from a documented error contract.

## AI-Missed Issue

One issue missed by generated code was the async pytest fixture configuration. The generated fixture used a decorator that was incompatible with the active strict pytest-asyncio configuration, so the tests failed during setup. The problem was identified through actual test execution and corrected by using the pytest-asyncio fixture decorator. This reinforced that generated code and Copilot completion messages were not treated as substitutes for runtime verification.
