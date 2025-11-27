# Command Pipeline Migration Notes

## Overview

The new command pipeline introduces a policy-driven architecture that consolidates
detection, routing, and state mutation. Key highlights:

- **Tail-only detection**: Commands are recognised only when the final non-blank user
  content ends with a command token. Commands in the middle of a message are treated as
  plain text unless strict detection is disabled.
- **Policy abstraction**: `CommandPolicyService` governs static-route enforcement,
  interactive-command disablement, strict detection defaults, and prefix resolution.
- **Secure state access**: `CommandStateService` exposes session state through secure
  adapters so commands no longer reach into repositories directly.
- **Handler alignment**: Interactive handlers (`set`, `model`, `unset`, failover) now
  delegate entirely to domain commands while receiving policy inputs via dependency
  injection.

## Migration Guidance

1. **Update fixtures/tests**: Use `tests.utils.command_service_utils.build_new_command_service`
   to obtain fully wired command services. Remove bespoke instantiation of
   `NewCommandService` and ad-hoc monkey patches.
2. **Tail commands in tests**: When asserting command execution, ensure sample messages
   place the interactive command at the end of the final user segment. Mid-sentence
   commands should now be asserted as non-executed regressions.
3. **Environment overrides**: Tests relying on static routing or interactive disablement
   should exercise `CommandPolicyService` behaviours via config/app-state instead of
   touching `os.environ` directly.
4. **Fallback behaviour**: Legacy fixtures that simulate command execution by stubbing
   `process_messages` can be deleted. The shared builder provides consistent behaviour
   across unit and integration tests.

This document will be expanded as downstream teams migrate their scenarios. For
additional context see `CHANGELOG.md` (2025-10-16 entry).
