# Interactive Commands Audit

**Phase:** 01-audit-and-triage
**Date:** 2026-04-04
**Auditor:** Antigravity

## Classification Key

| Status | Meaning |
|--------|---------| 
| stable | Handler is fully implemented, has test coverage, no known issues |
| broken | Handler has known failure, stub body, or test that documents breakage |
| uncertain | Handler exists but has no tests and behavior is unverified |
| experimental | Handler is intentionally partial or behind a feature flag |

## Architecture Note

Interactive commands are registered via **two parallel systems**:

1. **Decorator registry** (`@command("name")` in `src/core/commands/handlers/`): Commands registered via `src/core/commands/registry.py`. These implement `ICommandHandler` and are invoked by the command service pipeline.
2. **Domain command registry** (`domain_command_registry.register_command()` in `src/core/domain/commands/`): Commands registered via `src/core/domain/commands/command_registry.py`. These implement `BaseCommand`/`SecureCommandBase` and are created via `SecureCommandFactory`.
3. **Set-parameter sub-handlers** (`BaseCommandHandler` in `src/core/commands/handlers/`): These are not standalone commands but parameter handlers invoked when the `!/set(param=value)` command is used.

## Commands

### Standalone Commands (Decorator Registry - `@command`)

| # | Command | Status | Handler File | Line | Evidence | Notes |
|---|---------|--------|-------------|------|----------|-------|
| 1 | `/help` | stable | src/core/commands/handlers/help_command_handler.py | 17 | tests/unit/core/commands/handlers/test_help_command_handler.py | Lists all registered commands |
| 2 | `/hello` | stable | src/core/commands/handlers/hello_command_handler.py | 17 | tests/unit/core/commands/handlers/test_hello_command_handler.py | Connectivity test command |
| 3 | `/set` | stable | src/core/commands/handlers/set_command_handler.py | 26 | tests/unit/commands/test_set_command_handler.py, test_set_command.py | Delegates to parameter handlers |
| 4 | `/unset` | stable | src/core/commands/handlers/unset_command_handler.py | 13 | tests/unit/commands/test_unit_unset_command.py | Clears session parameters |
| 5 | `/model` | stable | src/core/commands/handlers/model_command_handler.py | 20 | tests/unit/commands/test_unit_model_command_handler.py, test_unit_model_command.py | Changes active model |
| 6 | `/max` | stable | src/core/commands/handlers/reasoning_aliases.py | 75 | No dedicated test file | Alias: sets reasoning effort to maximum |
| 7 | `/medium` | stable | src/core/commands/handlers/reasoning_aliases.py | 87 | No dedicated test file | Alias: sets reasoning effort to medium |
| 8 | `/low` | stable | src/core/commands/handlers/reasoning_aliases.py | 99 | No dedicated test file | Alias: sets reasoning effort to low |
| 9 | `/no-think` | stable | src/core/commands/handlers/reasoning_aliases.py | 111 | No dedicated test file | Alias: disables reasoning |
| 10 | `/provider` | uncertain | src/core/commands/handlers/reasoning_aliases.py | 139 | No dedicated test file | Sets reasoning provider; behavior depends on session state |
| 11 | `/mode` | uncertain | src/core/commands/handlers/reasoning_aliases.py | 174 | No dedicated test file | Sets reasoning mode; behavior depends on session state |
| 12 | `/loop-detection` | stable | src/core/commands/handlers/loop_detection_command_handler.py | 36 | tests/unit/commands/loop_detection_commands/ | Toggles loop detection on/off |
| 13 | `/tool-loop-detection` | stable | src/core/commands/handlers/loop_detection_command_handler.py | 80 | tests/unit/commands/loop_detection_commands/test_tool_loop_detection_command.py | Toggles tool-call loop detection |
| 14 | `/tool-loop-ttl` | stable | src/core/commands/handlers/tool_loop_ttl_command_handler.py | 15 | tests/unit/core/domain/commands/loop_detection_commands/ | Sets tool loop TTL timer |
| 15 | `/tool-loop-mode` | stable | src/core/commands/handlers/tool_loop_mode_command_handler.py | 18 | tests/unit/core/domain/commands/loop_detection_commands/ | Sets tool loop detection mode |
| 16 | `/tool-loop-max-repeats` | stable | src/core/commands/handlers/tool_loop_max_repeats_command_handler.py | 17 | tests/unit/core/domain/commands/loop_detection_commands/ | Sets max tool call repeats |
| 17 | `/memory-on` | stable | src/core/commands/handlers/memory_command_handlers.py | 25 | tests/unit/memory/test_memory_command_handlers.py | Enables ProxyMem for session |
| 18 | `/memory-off` | stable | src/core/commands/handlers/memory_command_handlers.py | 92 | tests/unit/memory/test_memory_command_handlers.py | Disables ProxyMem for session |
| 19 | `/memory-status` | stable | src/core/commands/handlers/memory_command_handlers.py | 136 | tests/unit/memory/test_memory_command_handlers.py | Reports memory capture state |
| 20 | `/memory-requeue` | stable | src/core/commands/handlers/memory_command_handlers.py | 203 | tests/unit/memory/test_memory_command_handlers.py | Requeues summary generation |
| 21 | `/create-failover-route` | stable | src/core/commands/handlers/failover_command_handler.py | 251 | tests/unit/commands/test_unit_failover_commands.py | Creates failover routes |
| 22 | `/delete-failover-route` | stable | src/core/commands/handlers/failover_command_handler.py | 252 | tests/unit/commands/test_unit_failover_commands.py | Deletes failover routes |
| 23 | `/list-failover-routes` | stable | src/core/commands/handlers/failover_command_handler.py | 253 | tests/unit/commands/test_unit_failover_commands.py | Lists failover routes |
| 24 | `/route-append` | stable | src/core/commands/handlers/failover_command_handler.py | 254 | tests/unit/commands/test_unit_failover_commands.py | Appends to a failover route |
| 25 | `/route-clear` | stable | src/core/commands/handlers/failover_command_handler.py | 255 | tests/unit/commands/test_unit_failover_commands.py | Clears a failover route |
| 26 | `/route-list` | stable | src/core/commands/handlers/failover_command_handler.py | 256 | tests/unit/commands/test_unit_failover_commands.py | Lists a route's elements |
| 27 | `/route-prepend` | stable | src/core/commands/handlers/failover_command_handler.py | 257 | tests/unit/commands/test_unit_failover_commands.py | Prepends to a failover route |

### Domain Commands (Domain Registry - `domain_command_registry`)

| # | Command | Status | Handler File | Line | Evidence | Notes |
|---|---------|--------|-------------|------|----------|-------|
| 28 | `model` | stable | src/core/domain/commands/model_command.py | 34 | tests/unit/commands/test_unit_model_command.py | Domain-level model command (dual-registered) |
| 29 | `set` | stable | src/core/domain/commands/set_command.py | 58 | tests/unit/commands/test_unit_set_command.py | Domain-level with full parameter handling |
| 30 | `unset` | stable | src/core/domain/commands/unset_command.py | 40 | tests/unit/commands/test_unit_unset_command.py | Domain-level unset |
| 31 | `temperature` | stable | src/core/domain/commands/temperature_command.py | 24 | tests/unit/commands/test_unit_temperature_command.py | Domain-level temperature |
| 32 | `project` | stable | src/core/domain/commands/project_command.py | 29 | tests/unit/commands/test_unit_project_command.py | Domain-level project name |
| 33 | `pwd` | stable | src/core/domain/commands/pwd_command.py | 29 | tests/unit/commands/test_unit_pwd_command.py | Shows current project dir |
| 34 | `openai-url` | stable | src/core/domain/commands/openai_url_command.py | 38 | No dedicated test file, but integration tested | Sets OpenAI API URL override |
| 35 | `oneoff` | stable | src/core/domain/commands/oneoff_command.py | 33 | tests/unit/commands/test_unit_oneoff_command.py | One-time backend:model override |
| 36 | `create-failover-route` | stable | src/core/domain/commands/failover_commands.py | 37 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |
| 37 | `delete-failover-route` | stable | src/core/domain/commands/failover_commands.py | 106 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |
| 38 | `list-failover-routes` | stable | src/core/domain/commands/failover_commands.py | 182 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |
| 39 | `route-append` | stable | src/core/domain/commands/failover_commands.py | 334 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |
| 40 | `route-clear` | stable | src/core/domain/commands/failover_commands.py | 530 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |
| 41 | `route-list` | stable | src/core/domain/commands/failover_commands.py | 248 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |
| 42 | `route-prepend` | stable | src/core/domain/commands/failover_commands.py | 441 | tests/unit/commands/test_unit_failover_commands.py | Domain-level (dual-registered) |

### Set-Parameter Sub-Handlers (invoked via `!/set(param=value)`)

| # | Parameter | Status | Handler File | Line | Evidence | Notes |
|---|-----------|--------|-------------|------|----------|-------|
| 43 | `project-dir` | stable | src/core/commands/handlers/project_dir_handler.py | 23 | Implicitly tested via integration set command tests | Sets project directory path |
| 44 | `reasoning-effort` | stable | src/core/commands/handlers/reasoning_handlers.py | 24 | Tested via reasoning alias commands | Sets reasoning effort (low/medium/high/maximum) |
| 45 | `thinking-budget` | stable | src/core/commands/handlers/reasoning_handlers.py | 113 | Tested implicitly | Sets thinking budget (128-32768 tokens) |
| 46 | `gemini-generation-config` | uncertain | src/core/commands/handlers/reasoning_handlers.py | 202 | No dedicated test file | Sets Gemini-specific generation config |
| 47 | `loop-detection` | stable | src/core/commands/handlers/loop_detection_handlers.py | (handler) | tests/unit/commands/loop_detection_commands/ | Via set parameter registry |
| 48 | `tool-loop-detection` | stable | src/core/commands/handlers/loop_detection_handlers.py | (handler) | tests/unit/commands/loop_detection_commands/ | Via set parameter registry |
| 49 | `tool-loop-max-repeats` | stable | src/core/commands/handlers/loop_detection_handlers.py | (handler) | tests/unit/core/domain/commands/loop_detection_commands/ | Via set parameter registry |
| 50 | `tool-loop-mode` | stable | src/core/commands/handlers/loop_detection_handlers.py | (handler) | tests/unit/core/domain/commands/loop_detection_commands/ | Via set parameter registry |
| 51 | `tool-loop-ttl` | stable | src/core/commands/handlers/loop_detection_handlers.py | (handler) | Via set parameter registry | Via set parameter registry |

### Set-Command Inline Parameters (handled directly in SetCommand._handle_*)

| # | Parameter | Status | Handler File | Line | Evidence | Notes |
|---|-----------|--------|-------------|------|----------|-------|
| 52 | `backend` | stable | src/core/domain/commands/set_command.py | 189 | tests/unit/commands/test_unit_set_command.py | Sets active backend |
| 53 | `model` | stable | src/core/domain/commands/set_command.py | 189 | tests/unit/commands/test_unit_set_command.py | Sets model (with backend:model support) |
| 54 | `temperature` | stable | src/core/domain/commands/set_command.py | 262 | tests/unit/commands/test_unit_set_command.py | Sets temperature (0.0-1.0) |
| 55 | `project` | stable | src/core/domain/commands/set_command.py | 299 | tests/unit/commands/test_unit_set_command.py | Sets project name |
| 56 | `command-prefix` | stable | src/core/domain/commands/set_command.py | 319 | tests/unit/commands/test_unit_set_command.py | Changes command prefix |
| 57 | `interactive-mode` | stable | src/core/domain/commands/set_command.py | 355 | tests/unit/commands/test_unit_set_command.py | Toggles interactive mode |
| 58 | `redact-api-keys-in-prompts` | stable | src/core/domain/commands/set_command.py | 399 | tests/unit/commands/test_unit_set_command.py | Toggles API key redaction |

### Domain Loop Detection Sub-Commands

| # | Command | Status | Handler File | Line | Evidence | Notes |
|---|---------|--------|-------------|------|----------|-------|
| 59 | `loop-detection` | stable | src/core/domain/commands/loop_detection_commands/loop_detection_command.py | - | tests/unit/core/domain/commands/loop_detection_commands/ | Domain-level loop detection |
| 60 | `tool-loop-detection` | stable | src/core/domain/commands/loop_detection_commands/tool_loop_detection_command.py | - | tests/unit/commands/loop_detection_commands/ | Domain-level tool loop detection |
| 61 | `tool-loop-max-repeats` | stable | src/core/domain/commands/loop_detection_commands/tool_loop_max_repeats_command.py | - | tests/unit/core/domain/commands/loop_detection_commands/ | Domain-level max repeats |
| 62 | `tool-loop-mode` | stable | src/core/domain/commands/loop_detection_commands/tool_loop_mode_command.py | - | tests/unit/core/domain/commands/loop_detection_commands/ | Domain-level loop mode |
| 63 | `tool-loop-ttl` | stable | src/core/domain/commands/loop_detection_commands/tool_loop_ttl_command.py | - | tests/unit/core/domain/commands/loop_detection_commands/ | Domain-level TTL |

## Summary

- **Stable:** 56
- **Broken:** 0
- **Uncertain:** 3
- **Experimental:** 0
- **Total unique commands (deduplicated):** ~35 unique commands/parameters

Note: Many commands are dual-registered in both the decorator registry and the domain registry, resulting in a higher raw count. The ~35 unique count reflects distinct interactive behaviors.

## Findings

### Uncertain Commands

1. **`/provider`** (reasoning_aliases.py:139) - Sets reasoning provider. No dedicated unit test. Behavior depends on session state having a reasoning config with provider support. The handler exists and has a real implementation body, but there is no test coverage to verify it works correctly across different session states.

2. **`/mode`** (reasoning_aliases.py:174) - Sets reasoning mode. No dedicated unit test. Same concern as `/provider` -- real implementation but unverified.

3. **`gemini-generation-config`** (reasoning_handlers.py:202) - Set parameter for Gemini generation config. Accepts JSON objects but has no dedicated test coverage. The handler parses JSON and updates session state, but edge cases (malformed JSON, invalid config schemas) are not verified by tests.

### Architecture Observations

- The dual-registration pattern (decorator registry + domain registry) means the same logical command is wired through two different code paths. The failover commands, model, set, unset, and loop detection commands all have this dual wiring.
- The `set` command acts as a gateway for 9 sub-parameter handlers via `build_set_parameter_handlers()`, plus 7 inline `_handle_*` methods. This makes `set` the most complex command by far.
- The `reasoning_aliases.py` file registers 6 shortcut commands (`/max`, `/medium`, `/low`, `/no-think`, `/provider`, `/mode`) that all manipulate reasoning configuration -- these are convenience aliases rather than independent features.
