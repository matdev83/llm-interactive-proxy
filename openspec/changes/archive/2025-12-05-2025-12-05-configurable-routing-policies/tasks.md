# Tasks - Configurable Routing Policies

- [ ] Define configuration model for routing policies in `AppConfig` (`RoutingConfig`).
- [ ] Add CLI arguments for disabling routing methods in `src/core/cli.py` (or where args are parsed).
- [ ] Implement configuration loading logic (CLI > Env > Config File).
- [ ] Update `BackendRoutingService` to inject `AppConfig` (or `RoutingConfig`).
- [ ] Implement enforcement logic in `BackendRoutingService.resolve_backend_instance`.
- [ ] Add unit tests for `BackendRoutingService` with different routing configurations.
- [ ] Verify behavior with integration tests or reproduction scripts.
- [ ] Update documentation to reflect new configuration options.
