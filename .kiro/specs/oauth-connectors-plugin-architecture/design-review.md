# Design Review Summary

**Feature**: `oauth-connectors-plugin-architecture`  
**Review status**: **Resolved** (as of 2026-04-15)  
**Design document**: [`design.md`](design.md)  
**Metadata**: [`spec.json`](spec.json) -- requirements, design, and tasks marked approved; `ready_for_implementation` set per Kiro spec state linter rules (no partial-approval deadlock with unchecked task checkboxes).

The technical design addresses decoupling of OAuth-oriented backends from core execution, discovery heuristics, and CLI wiring. **Significant updates** were made to all spec files (2026-04-15) following a comprehensive cross-check audit against the live codebase.

## Previously raised issues (updated 2026-04-15)

| Issue | Resolution in `design.md` |
|-------|---------------------------|
| CLI hook timing vs parser build | **Lifecycle ordering** documented: `cli.py` import pulls in `backend_imports`, which runs `discover_backends()` (including `discover_plugin_backends()`) **before** `main()` → `parse_cli_args()` → `ArgumentParserBuilder.build()`; alternate imports called out for tests/tools. |
| Plugin dependency direction for protocols | **`ITokenRefresher` / `ICredentialRotator` / `IOAuthAccountSelector`**: definitions live under `src/core/interfaces/` for core use; **must be re-exported** from `src/core/plugin_api.py` so external packages never deep-import `src.core.interfaces`. |
| Parsed CLI args not applied to config | **`config_applicator_hook`** on `BackendPluginDefinition`; **`ConfigurationApplicator`** iterates hooks as post-applicator phase via domain-specific applicator pipeline. |

## Cross-check audit findings (2026-04-15)

All findings from the codebase cross-check audit have been resolved in the spec files:

| Finding | Resolution |
|---------|------------|
| **P0**: `ITokenRefresher` already exists in `streaming_executor.py` but was not acknowledged | `ITokenRefresher` is now relocated to `src/core/interfaces/`; `ICredentialRotator` extends it. Full relationship documented in `design.md`. |
| **P0**: `record_rate_limit` duck-typed access not covered by protocols | Added `record_rate_limit()` method to `ICredentialRotator`. Migration path table added. |
| **P1**: `IOAuthAccountSelector` method names didn't match current access patterns | Method names documented with migration notes from current attribute/method mix. |
| **P1**: 3 additional OAuth CLI flags not classified | Explicitly classified as **deferred** in `requirements.md` with rationale. |
| **P2**: `ConfigurationApplicator` pipeline integration unclear | Post-applicator phase approach documented; 15+ applicator architecture acknowledged. |
| **P2**: YAML config template updates missing | Explicit task added (task 1.2) for in-repo backend YAML updates. |
| **P2**: `test_vendor_prefix.py` imports OAuth package | Added to tasks 4.1 and requirements 5.2. |
| **P3**: `oauth_detector.py` partial dynamic capability not acknowledged | Acknowledged in all spec files; entry-point discovery noted. |
| **P3**: `scope.py` extent underrepresented | Full 7-entry frozenset + substring fallback + config overrides documented. |
| **P3**: `backend_discovery_state.py` storage mechanics unspecified | Storage pattern specified (parallel dicts, lock, register/get/clear functions). |
| **P3**: Phase 2/3 parallelism not addressed | Phase parallelism note added to tasks.md. |

## Design strengths (retained)

1. Extending **`BackendCapabilityDescriptor`** reuses the existing capability pattern instead of inventing parallel registries.
2. **Test isolation** targets real coupling (`importorskip`, connector-specific tests) while allowing a narrow **packaging contract** exception (see `requirements.md` section 5).
3. **Migration path table** in `design.md` provides a concrete mapping from current duck-typed access patterns to protocol methods.

## Outstanding design polish (non-blocking for design approval)

Tracked in `design.md` and `requirements.md` rather than as gate items:

- **Scope boundary**: Initial implementation focuses on headline paths; additional `backend_type` string heuristics elsewhere are listed under **Deferred scope** in `requirements.md` (now with explicit classification of 3 deferred CLI flags).
- **REQ 4.3**: Plugin-owned config schema extension is specified at the design level (hook + documentation); full dynamic Pydantic merge may evolve during implementation.
- **`Protocol` runtime checks**: Prefer methods over `@property` on `@runtime_checkable` protocols (see `design.md`). `IOAuthAccountSelector` `@runtime_checkable` is optional.
- **Cross-repo versioning**: `PluginCompatibility` has `core_min_version`/`core_max_version` but runtime version comparison is not yet defined.
- **Pre-import OAuth filter vs YAML**: Normative section in `requirements.md` plus `design.md` pre-import table and optional `BackendPluginDefinition` registration flags document how `connectors/__init__.py` can honor capability semantics before module import.

## Final assessment

**Decision**: **GO** for implementation (`spec.json` marks requirements, design, and tasks **approved**; `ready_for_implementation` is **true**).

**Rationale**: Critical lifecycle, plugin API boundary, ITokenRefresher reconciliation, configuration application, pre-import capability equivalence, and CLI ordering (default vs alternate paths) are captured. Earlier P0/P1 audit findings remain resolved. Residual items are follow-up scope (deferred modules, runtime semver checks) and normal implementation hardening.

**Next steps**: Execute `tasks.md` under the project’s Kiro `/kiro:spec-impl` or standard engineering workflow; run `/kiro:validate-design` or repository checks if the team requires a fresh validation stamp after substantive spec edits.
