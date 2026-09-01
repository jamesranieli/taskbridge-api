# Copilot Tool Strategy

## Usage Entries

| # | Copilot Feature | Where Used | Strategy and Result |
|---|---|---|---|
| 1 | Repository custom instructions | `.github/copilot-instructions.md` | Established Python, FastAPI, SQLAlchemy ORM, layered architecture, validation, tenant isolation, typed contracts, logging, and audit immutability as repository-wide guidance. |
| 2 | Copilot coding agent | Initial Project Service | Generated the required low-effort baseline first, preserving it unreviewed before architectural remediation. |
| 3 | Copilot Chat | Project review and remediation | Used conversational review to identify architecture, security, validation, tenant-isolation, logging, and error-handling concerns, followed by human verification. |
| 4 | Copilot coding agent | Audit and Notification implementation | Generated implementation from the previously written SPEC.md so the code was constrained by explicit contracts rather than an open-ended request. |
| 5 | Copilot Chat | Mid-sprint scope analysis | Helped analyze the `MILESTONE_REOPENED` and actor-IP change before implementation; human review corrected invented assumptions and privacy concerns. |
| 6 | Copilot coding agent | Required tests | Generated the six required assessment scenarios; execution then exposed an async fixture problem that required correction. |
| 7 | Copilot Chat | Debugging | Used actual pytest output to diagnose the fixture decorator problem instead of asking Copilot to speculate about a passing implementation. |
| 8 | Copilot repository/code context | API design | Inspected existing service signatures and repository structure before accepting typed FastAPI schemas and routes. |
| 9 | Copilot coding agent | FastAPI layer | Proposed database dependencies, schemas, and routes; generated output was compared against the real repository before acceptance. |
| 10 | Copilot code review / review workflow | Human verification workflow | Generated changes were treated as review candidates rather than authoritative output; repository state, diffs, tests, and route registration were independently checked before acceptance. |

The workflow therefore used at least four distinct Copilot capabilities or usage modes: repository custom instructions, Copilot Chat, the Copilot coding agent/code-change workflow, and Copilot repository/code-review context.

## Scenario Responses

**When Copilot generates code that appears correct:** I compare it with the current repository contracts and architecture before accepting it. I then run the relevant tests or import checks. Generated code is not considered complete merely because Copilot reports success.

**When Copilot conflicts with the specification:** The written specification and assessment requirements take precedence. I use a corrective prompt containing the exact required terminology or contract and reject incompatible generated changes.

**When Copilot references stale or nonexistent code:** I constrain the next prompt to the current repository and provide exact filenames, model fields, or service signatures when necessary. I verify the resulting diff against the working tree.

**When runtime behavior disagrees with Copilot's prediction:** Runtime evidence wins. I provide the real error or failing test back to Copilot, make the smallest justified correction, and rerun the test.

**When a generated change has security or privacy implications:** I manually evaluate tenant isolation, authorization, logging, and data exposure. For actor IP, this resulted in retaining only the required audit value while preventing the raw address from appearing in validation errors or logs.

## Observed Copilot Limitations

1. **Stale repository context:** Copilot referenced deleted or previous implementations while reviewing the Project Service and later proposed API code for modules and structures that did not exist in the current repository.
2. **Over-generation and specification drift:** The initial Project generation exceeded the requested scope, the impact analysis altered the exact `MILESTONE_REOPENED` requirement, and test generation initially needed tighter constraints to match the required scenarios.
3. **Generated code still required runtime correction:** The async pytest fixture used an incompatible decorator, which was only discovered by executing the tests.
4. **Architecture and type hallucinations:** API proposals included a parallel application structure, synchronous database sessions, UUID assumptions for integer Project IDs, and incorrect imports despite an existing async architecture.
5. **Security/privacy judgment was incomplete:** Copilot-generated behavior could expose a raw actor IP in an error/logging path until human review constrained that behavior.
6. **Agent completion reports were not reliable evidence of repository state:** During API work, Copilot reported that changes were applied even when the working tree had not changed. Repository status, commit history, and diffs had to be checked independently.

## Overall Strategy

Copilot was most effective as an accelerator for generation, review, and iteration when bounded by explicit repository instructions and written contracts. Human judgment remained responsible for architecture, security, privacy, scope control, acceptance of generated changes, and interpretation of runtime evidence. The final implementation was accepted based on repository inspection and executable tests rather than Copilot's confidence or completion messages.
