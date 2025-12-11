# Research & Design Decisions Template

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `<feature-name>`
- **Discovery Scope**: New Feature / Extension / Simple Addition / Complex Integration
- **Key Findings**:
  - Finding 1
  - Finding 2
  - Finding 3

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/interfaces/` - Existing interface patterns
  - `src/core/services/` - Service implementation patterns
  - `src/connectors/` - Backend adapter patterns
  - `src/core/app/stages/` - Initialization sequence
- **Patterns Identified**:
  - DI registration with factory functions
  - Interface segregation (I-prefix convention)
  - Error hierarchy extending `LLMProxyError`
  - Async/await for all I/O operations
- **Implications**: How this affects the new feature design

### [Topic or Question]
- **Context**: What triggered this investigation?
- **Sources Consulted**: Links, documentation, API references, benchmarks
- **Findings**: Concise bullet points summarizing the insights
- **Implications**: How this affects architecture, contracts, or implementation

_Repeat the subsection for each major topic._

## Architecture Pattern Evaluation
List candidate patterns or approaches that were considered. Use the table format where helpful.

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Service + Interface | New service with DI registration | Follows existing patterns, testable | Additional boilerplate | Recommended |
| Middleware | Request/response pipeline integration | Transparent to callers | Order dependencies | For cross-cutting |
| Connector Extension | Extend `LLMBackend` base | Backend-specific logic | Couples to base class | For new backends |
| Direct Integration | Modify existing service | Fastest implementation | Violates SRP, harder to test | Avoid |

## Design Decisions
Record major decisions that influence `design.md`. Focus on choices with significant trade-offs.

### Decision: `<Title>`
- **Context**: Problem or requirement driving the decision
- **Alternatives Considered**:
  1. Option A - short description
  2. Option B - short description
- **Selected Approach**: What was chosen and how it works
- **Rationale**: Why this approach fits the current project context
- **Trade-offs**: Benefits vs. compromises
- **Follow-up**: Items to verify during implementation or testing

### Decision: DI Lifetime Selection
- **Context**: Choosing between Singleton, Scoped, and Transient lifetimes
- **Guidelines**:
  - **Singleton**: Stateless services, caches, configuration holders
  - **Scoped**: Per-request state, session-bound data
  - **Transient**: Stateful per-use, lightweight factories
- **Selected Approach**: [Based on feature requirements]
- **Rationale**: [Why this lifetime fits]

### Decision: Error Handling Strategy
- **Context**: How to handle and propagate errors
- **Guidelines**:
  - Extend `LLMProxyError` for domain errors
  - Use appropriate HTTP status codes
  - Never catch bare `Exception`
  - Log with `exc_info=True`
- **Selected Approach**: [Specific exceptions to create]

_Repeat the subsection for each decision._

## Testing Strategy Research

### Existing Test Patterns
- Unit tests in `tests/unit/` with mocked dependencies
- Integration tests in `tests/integration/` with DI container
- Property tests in `tests/property/` using Hypothesis
- Behavior tests in `tests/behavior/` for scenarios

### Test Infrastructure
- Fixtures in `tests/conftest.py`
- Mock backends in `tests/mocks/`
- Test utilities in `tests/utils/`

### Coverage Requirements
- Target: [percentage or focus areas]
- Critical paths: [list]
- Edge cases: [list]

## Risks & Mitigations
- Risk 1: [Description] - Mitigation: [Approach]
- Risk 2: [Description] - Mitigation: [Approach]
- Risk 3: [Description] - Mitigation: [Approach]

## Performance Considerations
- Async I/O impact: [analysis]
- Memory footprint: [analysis]
- Wire capture overhead: [if applicable]

## References
Provide canonical links and citations (official docs, standards, ADRs, internal guidelines).
- [FastAPI Dependency Injection](https://fastapi.tiangolo.com/tutorial/dependencies/) - DI patterns
- [Python ABC](https://docs.python.org/3/library/abc.html) - Interface definitions
- Project `AGENTS.md` - Development guidelines
- Project `src/core/common/exceptions.py` - Error hierarchy
- ...
