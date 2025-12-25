# Requirements Document

## Project Description (Input)
Harden and complete the typed data contracts refactor (follow-up to `.kiro/specs/cross-layer-typed-data-contracts`) by eliminating remaining `Any` / `dict[str, Any]` boundary leaks across Transport ↔ Core ↔ Connector seams, converging on canonical contracts (`RequestContext`, `CanonicalChatRequest`, `BackendTarget`, `UsageSummary`, typed streaming and capture contracts), and making `dev/scripts/check_boundary_types.py` pass (or explicitly allowlist/document any remaining exceptions) without changing externally observable API behavior.

## Requirements
<!-- Will be generated in /kiro:spec-requirements phase -->

