# Refactoring Status: Consolidated SOLID Refactor

This file is the single source of truth for the SOLID/DIP refactor in `dev/`.

---

## Executive summary

The repository is mid-migration to a SOLID/DIP architecture. Foundational work (DI container, application factory, backend registration, configuration normalization) has progressed and fixed many systemic startup failures. A key ongoing effort is the systematic decoupling of core business logic from the FastAPI transport layer to improve testability and maintainability, with specific tasks outlined in the TODO section. Remaining work is focused on runtime/business-logic issues, test fixtures, interface drift, and streaming/async correctness.

Use this file as the canonical tracking point for progress, decisions, and remaining tasks. Update this file with short changelog entries when you apply fixes.

---

## Consolidated TODO (actionable items)

This is a detailed TODO list based on the recommended refactoring steps, organized in a logical sequence from immediate improvements to longer-term architectural changes:

**Phase 1: Decouple Core from FastAPI Dependencies**
- [ ] Create `RequestContext` class to decouple core from FastAPI `Request` objects.
- [ ] Update `RequestProcessor.process_request()` signature to accept `RequestContext` instead of FastAPI `Request`.
- [ ] Create adapter in controllers to convert FastAPI `Request` to `RequestContext`.
- [ ] Update tests to use `RequestContext` in `RequestProcessor` tests.

**Phase 2: Refactor Connectors**
- [ ] Refactor connectors to return domain objects (e.g., a `ChatResponse` model, `AsyncIterator[bytes]`) instead of transport-specific `Response` objects.
- [ ] Replace `HTTPException` in connectors with domain-specific exceptions (e.g., `BackendError`, `ConfigError`).

**Phase 3: Normalize Exception and Streaming Handling**
- [ ] Add exception mappers in the controller layer to translate domain exceptions to HTTP responses.
- [ ] Create `StreamingResponseEnvelope` interface in the core domain to represent streaming responses consistently.
- [ ] Normalize streaming handling in `ResponseProcessor` to use the new `StreamingResponseEnvelope` interface.

**Phase 4: Deeper Architectural Improvements**
- [ ] Create `ISessionResolver` interface and extract session extraction logic from `RequestProcessor`.
- [ ] Update DI container to register the new `SessionResolver` implementation.
- [ ] Audit command handlers that depend on `app.state` and replace with explicit dependency injection.
- [ ] Create a dedicated `transport` package with FastAPI-specific adapters for controllers and responses.

---

## Changelog

- 2025-08-26: **Command Testing Overhaul**: Refactored all interactive commands to use a new, robust testing architecture with isolated unit tests and comprehensive snapshot tests. Implemented command auto-discovery to replace the legacy hardcoded registry.
- 2025-08-17: Consolidated all `dev/*.md` into this file and archived originals to `dev/archive/`.
- 2025-08-19: Removed debug prints from production code, added adapter-based validation for backend/model in `SetCommand`, improved `CommandProcessor` state application, and archived dev notes.

---

Append additional changelog entries here after fixes and subsequent test runs.
