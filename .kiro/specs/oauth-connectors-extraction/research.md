# Research and Design Decisions: oauth-connectors-extraction

## Summary

Research confirms the codebase already contains most runtime primitives needed for safe extraction (unified routing, B2BUA boundary isolation, constrained-family policy). The primary work is boundary and packaging formalization:
- move OAuth/sensitive connectors to optional external package
- add entry-point plugin discovery with fail-open semantics
- harden and verify decoupling contracts for backend and frontend integration layers

## Research Scope

- Active spec files under `.kiro/specs/oauth-connectors-extraction/`
- Current routing/session architecture in `src/core/services/`
- Startup/discovery path in `src/connectors/__init__.py` and bootstrap services
- Constrained policy and semantic validation in `src/core/config/`
- Unified routing compliance gate artifacts under `dev/routing/` and `dev/scripts/`
- Commit history from this week (B2BUA/session handling, unified routing, constrained connector validation)

## Discovery Findings

### 1) Startup and Connector Discovery
- Current discovery auto-imports local connector modules via `pkgutil.iter_modules` in `src/connectors/__init__.py`.
- No current runtime discovery of external entry points under `llm_proxy_backends`.
- OAuth filtering for multi-user mode exists, but it is not equivalent to optional external plugin package detection.

### 2) Unified Routing Is Already Centralized
- Shared routing stack exists:
  - `src/core/services/backend_model_resolver.py`
  - `src/core/services/backend_routing_service.py`
- Compliance guard exists and is wired as explicit check artifact:
  - `dev/routing/unified_routing_inventory.yaml`
  - `dev/scripts/check_routing_unification_compliance.py`
- Inventory includes primary, verifier, replacement, auxiliary, and selected connector-internal outbound surfaces.

### 3) B2BUA Boundary Isolation Is Already Enforced
- `src/core/services/backend_completion_flow/completion_session_resolver.py`
  - B2BUA mode uses A-leg for session continuity resolution.
- `src/core/services/backend_completion_flow/backend_request_preparer.py`
  - connector-facing `session_id` uses B-leg when B2BUA identity exists.
- `src/core/services/connector_invoker.py`
  - strips sensitive identity fields (`a_session_id`, `client_session_id`, `auth_scope_id`) from connector-facing context.

### 4) Frontend Adapter Separation Exists but Is Not Explicitly Contracted in This Spec
- Controllers/protocol adapters largely depend on interfaces and canonical request-processing boundaries:
  - `src/core/app/controllers/chat_controller.py`
  - `src/core/app/controllers/anthropic_controller.py`
  - `src/core/app/controllers/responses_controller.py`
- This supports the target contract that core business services remain protocol-agnostic.

### 5) Constrained Connector-Family Policy Exists and Is Shared
- Policy source and matching:
  - `src/core/config/constrained_backend_policy.py`
- Semantic validation and runtime checks:
  - `src/core/config/semantic_validation.py`
- Families include explicit/wildcard rules (`qwen-oauth`, `gemini-oauth*`, `antigravity*`).

### 6) Weekly Refactor Signals Relevant to This Spec
- Commits indicate recent architecture movement around:
  - B2BUA-like session handling and continuity
  - unified routing and compliance guardrails
  - constrained OAuth connector instance validation
- Implication: this spec must avoid reintroducing older assumptions (for example monolithic backend service-centric routing language).

## Decisions

### D1: Keep Optional Extraction as First-Class Package Contract
- Extracted OAuth connectors are defined as separate package (`llm-interactive-proxy-oauth-connectors`).
- Core package provides optional install extra (`llm-interactive-proxy[oauth]`).

### D2: Use Entry-Point Discovery for Optional Plugin Activation
- Group name: `llm_proxy_backends`.
- No entry points and entry-point load failures are non-fatal startup states.

### D3: Preserve Resolver-Centric Unified Routing
- Extraction must not introduce alternative routing paths.
- All outbound call surfaces continue using shared routing boundary and compliance gate.

### D4: Preserve B2BUA Identity Boundary as Non-Regression Constraint
- A-leg remains internal continuity identity.
- B-leg remains connector-facing identity.
- Sensitive internal identity fields must not cross connector boundary.

### D5: Treat Core-to-Connector and Core-to-Frontend Decoupling as Explicit Requirements
- Core business logic depends on abstractions/contracts, not concrete connector classes.
- Frontend protocol adapters remain transport translators and do not own routing/session policy logic.

### D6: Keep Constrained-Family Policy Central and Reused
- Single-instance policy remains shared between semantic validation and routing behavior.
- Extraction cannot bypass or duplicate this policy.

### D7: Introduce Explicit Plugin Compatibility Contract
- Plugin activation should include compatibility metadata handling.
- Incompatible plugins are skipped with warnings, not startup-fatal errors.

### D8: Verification Must Cover Both Installation Modes
- Core-only mode (no oauth package) and core+oauth mode are both mandatory test targets.

## Risks and Mitigations

### Risk 1: Startup coupling regressions through import paths
- **Mitigation:** prohibit unconditional imports of extracted connectors in core startup/DI paths; enforce via focused tests and code review checklist.

### Risk 2: Hidden routing bypass introduced during extraction changes
- **Mitigation:** keep unified routing compliance gate mandatory; update inventory when new call surfaces are added.

### Risk 3: Identity leakage during connector boundary changes
- **Mitigation:** maintain B2BUA boundary tests validating no A-leg/internal field leakage to connector context.

### Risk 4: Optional package absence breaks operational continuity
- **Mitigation:** explicit acceptance criteria and tests for no-entrypoint/no-package states, plus API-key connector smoke coverage.

## Follow-Up Research Items

- Confirm final published package naming/versioning policy for `llm-interactive-proxy-oauth-connectors`.
- Finalize compatibility metadata shape for plugin entry points (minimum core version field and validation strategy).
- Define strict anti-coupling static checks for forbidden import directions between core services and extracted connector modules.
