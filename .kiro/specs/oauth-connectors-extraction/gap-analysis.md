# Gap Analysis: oauth-connectors-extraction (Post-Refactor Refresh)

## Executive Summary

The repository already contains major architecture assets that reduce extraction risk:
- resolver-centric unified routing with compliance gate
- B2BUA A-leg/B-leg identity isolation at connector boundary
- constrained single-instance connector-family policy
- protocol adapters mostly routed through canonical core interfaces

The largest remaining gaps are not foundational runtime primitives, but **contract hardening and packaging boundaries**:
- explicit optional plugin package discovery (`llm_proxy_backends`) is not yet implemented in core connector discovery path
- concrete OAuth connectors are still shipped inside `src/connectors/`
- optional-package absence behavior is only partially contractual and needs stronger acceptance coverage
- plugin API surface/version-compatibility contract is not formalized enough for out-of-tree connector lifecycle

**Effort:** M (4-7 days)  
**Risk:** Medium (startup/discovery and DI wiring are sensitive, but routing/session primitives already exist)

## 1. Current State Investigation (Evidence)

### 1.1 Architecture Assets Already Present
- **Unified routing and anti-bypass gate**
  - `src/core/services/backend_model_resolver.py`
  - `src/core/services/backend_routing_service.py`
  - `dev/routing/unified_routing_inventory.yaml`
  - `dev/scripts/check_routing_unification_compliance.py`
- **B2BUA boundary protection**
  - `src/core/services/connector_invoker.py` (`_project_context`)
  - `src/core/services/backend_completion_flow/backend_request_preparer.py` (`prepare_backend_kwargs`)
  - `src/core/services/backend_completion_flow/completion_session_resolver.py`
- **Constrained connector-family policy**
  - `src/core/config/constrained_backend_policy.py`
  - `src/core/config/semantic_validation.py`

### 1.2 Evidence of Remaining Coupling
- **Core connector discovery is local-module auto-import only**
  - `src/connectors/__init__.py` uses `pkgutil.iter_modules` and does not scan entry points.
- **OAuth connectors still live in core repository**
  - presence of `src/connectors/gemini_oauth_auto/`, `src/connectors/kiro_oauth_auto/`, `src/connectors/openai_codex/`, etc.
- **No current `llm_proxy_backends` discovery path**
  - no runtime usage of `importlib.metadata.entry_points(..., group="llm_proxy_backends")` in current source.

## 2. Requirement-to-Asset Mapping

Legend: **Present**, **Partial**, **Missing**

| Requirement Area | Status | Evidence | Gap |
|---|---|---|---|
| R1 Separate OAuth package & install UX | Partial | Existing spec intent only | Package split and optional extra contract not fully enforced in implementation/spec traceability |
| R2 Plugin discovery & optional availability detection | Missing | `src/connectors/__init__.py` local auto-discovery only | Entry-point discovery and no-entrypoints-as-valid behavior not implemented |
| R3 Core independence from concrete backend connectors | Partial | Routing/session services mostly abstraction-driven | Extracted connectors still in core tree; some DI/import boundaries remain connector-aware |
| R4 Core independence from frontend connector implementations | Partial | Controllers mostly use interfaces/request processor | Contract not explicitly codified in this spec set; coverage criteria incomplete |
| R5 Runtime behavior when OAuth package absent | Partial | Fail-open patterns exist in many services | Explicit startup/no-crash + API-key connector continuity acceptance criteria need stronger linkage |
| R6 Unified routing contract across outbound surfaces | Present | inventory + compliance gate + shared routing service | Spec needs to preserve this as non-regression requirement during extraction |
| R7 B2BUA identity isolation at connector boundary | Present | `ConnectorInvoker` and `BackendRequestPreparer` enforce B-leg/no A-leg leakage | Extraction plan must preserve these boundaries for plugin connectors |
| R8 Constrained single-instance policy | Present | constrained policy + semantic validation | Must ensure policy continuity after extracted connectors move to plugin |
| R9 Stable plugin API and compatibility contract | Partial | interface building blocks exist | Public plugin API and compatibility/versioning surface not finalized |
| R10 Layered/SOLID/DRY constraints | Partial | architecture direction is good | Explicit anti-drift checks and requirement traceability need reinforcement |
| R11 Verification and regression safety | Partial | many tests exist for routing/session behavior | Explicit package-present/package-absent matrix and plugin discovery tests need expansion |

## 3. Key Gap Details

### G1: No entry-point based plugin discovery in core
- Impacted requirements: `2.1-2.6`, `5.1-5.2`, `9.2`
- Risk: extracted package cannot be loaded dynamically; extraction remains conceptual.

### G2: Extraction boundary not physically enforced
- Impacted requirements: `1.1-1.4`, `3.1-3.5`
- Risk: core still ships and imports OAuth connectors, so dependency/ownership boundaries remain blurry.

### G3: Optional package absence behavior is not fully formalized
- Impacted requirements: `5.1-5.6`, `11.1-11.4`
- Risk: regressions could reintroduce startup coupling or degrade API-key connector continuity.

### G4: Plugin API compatibility contract is underspecified
- Impacted requirements: `9.1-9.4`
- Risk: plugin breakages can surface as runtime failures without deterministic compatibility handling.

### G5: Frontend-to-core decoupling is implicit, not explicitly guarded in this spec
- Impacted requirements: `4.1-4.4`, `10.1-10.4`
- Risk: protocol-specific logic may creep into core layers during future changes.

## 4. Implementation Options

### Option A: Big-bang extraction
- Move all targeted connectors out immediately and retrofit discovery/DI in one step.
- **Pros:** shortest elapsed path to separate package.
- **Cons:** highest rollout risk; difficult regression isolation.

### Option B: Hardening-only (no immediate move)
- Implement contracts and tests without moving connectors out yet.
- **Pros:** safest immediate runtime stability.
- **Cons:** does not deliver package separation objective soon enough.

### Option C: Staged hybrid (Recommended)
- Stage 1: define contracts and plugin discovery path + fail-open behaviors.
- Stage 2: migrate selected connectors + plugin packaging + optional extra.
- Stage 3: complete extraction and enforce anti-coupling regression checks.
- **Pros:** balanced risk and incremental verification.
- **Cons:** temporary dual-state complexity during migration window.

## 5. Complexity and Risk

- **Complexity:** Medium
  - discovery path extension
  - DI boundary hardening
  - packaging/extras split
  - regression test matrix (with and without optional package)
- **Risk:** Medium
  - startup breakage if discovery and validation order is wrong
  - hidden coupling via imports in bootstrap/registration code
  - inconsistent behavior between protocol adapters if routing contracts are bypassed

## 6. Recommendations for Design and Tasks Phases

1. Treat entry-point discovery and fail-open semantics as first milestone before moving files.
2. Preserve existing B2BUA and unified routing boundaries as non-regression constraints.
3. Define explicit plugin API surface and compatibility checks before external package publication.
4. Add explicit verification matrix:
   - core-only install (no oauth package)
   - core + oauth extra
   - missing extracted backend in config but healthy API-key backend present
5. Keep constrained-family policy and unified routing compliance gate mandatory throughout extraction.
