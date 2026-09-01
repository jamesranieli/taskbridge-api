# Copilot Tool Strategy

## Usage Entries

| # | Copilot Feature | Where Used | Strategy and Result |
|---|---|---|---|
| 1 | Repository custom instructions | `.github/copilot-instructions.md` | Established Python, FastAPI, SQLAlchemy ORM, layered architecture, validation, tenant isolation, typed contracts, logging, and audit immutability as repository-wide guidance. |
| 2 | Copilot coding agent | Initial Project Service | Generated the initial low-effort Project Service baseline, preserving the generated output before architectural remediation. |
| 3 | Copilot Chat | Project review and remediation | Used conversational review to identify architecture, security, validation, tenant-isolation, logging, and error-handling concerns, followed by human verification. |
| 4 | Copilot coding agent | Audit and Notification implementation | Generated implementation from the previously written SPEC.md so the code was constrained by explicit contracts rather than an open-ended request. |
| 5 | Copilot Chat | Mid-sprint scope analysis | Helped analyze the `MILESTONE_REOPENED` and actor-IP change before implementation; human review corrected invented assumptions and privacy concerns. |
| 6 | Copilot coding agent | Required tests | Generated the six required assessment scenarios; execution then exposed an async fixture problem that required correction. |
| 7 | Copilot Chat | Debugging | Used actual pytest output to diagnose the fixture decorator problem instead of asking Copilot to speculate about a passing implementation. |
| 8 | Copilot repository/code context | API design | Inspected existing service signatures and repository structure before accepting typed FastAPI schemas and routes. |
| 9 | Copilot coding agent | FastAPI layer | Proposed database dependencies, schemas, and routes; generated output was compared against the real repository before acceptance. |
| 10 | Copilot Chat with repository context | Human verification workflow | Generated changes were treated as review candidates rather than authoritative output; repository state, diffs, tests, and route registration were independently checked before acceptance. |

The workflow therefore used at least four distinct Copilot capabilities or usage modes: repository custom instructions, Copilot Chat, the Copilot coding agent/code-change workflow, and Copilot repository/code context.

## Scenario Responses

**Understanding a complex 600-line legacy service in an unfamiliar codebase before wiring a new service to it:** I would use Copilot Chat with repository/code context so Copilot can explain the existing service, dependencies, data flow, and contracts while referencing the actual code. I would still verify its explanation against the repository because stale or inferred context can be wrong.

**Generating consistent, standards-compliant request-validation middleware across 10 existing route handlers:** I would use repository custom instructions together with the Copilot coding agent/code-generation workflow. Custom instructions establish the shared validation and security rules, while the coding agent can apply the pattern consistently across multiple files.

**Quickly verifying whether a JWT verification implementation correctly handles token expiry and signature tampering:** I would use Copilot Chat as a focused code-review aid, supplying the implementation and asking it to check expiry and signature validation paths specifically. I would then verify the behavior with executable security-focused tests rather than relying only on Copilot's review.

**Enforcing that all commits to main pass linting and test coverage thresholds automatically, with no human intervention:** I would use GitHub Actions rather than Copilot as the enforcement mechanism, with Copilot assisting in drafting or reviewing the workflow. Copilot can help create the configuration, but CI branch-protection checks—not an AI assistant—must provide automatic enforcement.

**Reviewing a contractor's AI-generated service module for security vulnerabilities before it reaches staging:** I would use Copilot Chat/review with repository context and the project's custom instructions to check tenant isolation, authorization, data exposure, logging, validation, and architectural boundaries. I would treat the output as review input and independently verify every high-severity finding.

**Ensuring Copilot follows multi-tenant data isolation rules consistently across all developers and sessions:** I would use `.github/copilot-instructions.md` with explicit repository-wide tenant-isolation rules. Because those instructions travel with the repository, they provide persistent guidance across developers and Copilot sessions, although generated code still requires review and tests.

## Observed Copilot Limitations

1. **Stale repository context:** Copilot referenced deleted or previous implementations while reviewing the Project Service and later proposed API code for modules and structures that did not exist in the current repository.
2. **Over-generation and specification drift:** The initial Project generation exceeded the requested scope, the impact analysis altered the exact `MILESTONE_REOPENED` requirement, and test generation initially needed tighter constraints to match the required scenarios.
3. **Generated code still required runtime correction:** The async pytest fixture used an incompatible decorator, which was only discovered by executing the tests.
4. **Architecture and type hallucinations:** API proposals included a parallel application structure, synchronous database sessions, UUID assumptions for integer Project IDs, and incorrect imports despite an existing async architecture.
5. **Security/privacy judgment was incomplete:** Copilot-generated behavior could expose a raw actor IP in an error/logging path until human review constrained that behavior.
6. **Agent completion reports were not reliable evidence of repository state:** During API work, Copilot reported that changes were applied even when the working tree had not changed. Repository status, commit history, and diffs had to be checked independently.

## Overall Strategy

Copilot was most effective as an accelerator for generation, review, and iteration when bounded by explicit repository instructions and written contracts. Human judgment remained responsible for architecture, security, privacy, scope control, acceptance of generated changes, and interpretation of runtime evidence. The final implementation was accepted based on repository inspection and executable tests rather than Copilot's confidence or completion messages.
