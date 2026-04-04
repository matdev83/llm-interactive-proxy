# Brownfield Priorities

This file captures maintainer-provided planning guidance for the next milestone selection pass. It is intentionally higher level than requirements and does not define tasks or a roadmap.

## Must Not Break

- The codebase must move toward production-workload stability.
- Changes in non-core proxy features (for example context-window compression, random model replacement, interactive commands) must not break core functionality.
- Non-core feature work must not require changes in core proxy behavior or architecture.
- Main frontend connectors must remain stable and protocol-compliant: OpenAI chat completions, Anthropic, and Gemini.
- Main backend connectors must remain stable and protocol-compliant.
- Changes in the external OAuth connectors package must not cause regressions in proxy core.
- Core proxy functionality must not depend on connector-specific code or optional functional enhancements.
- In general, new or changed non-core functionality must not cause regressions in the core.

## What Hurts Most Now

- Minor instabilities still exist in less common code paths, including interrupted sessions.
- The functional state of interactive commands is unclear.
- The project still discovers new bugs in core behavior despite a huge test base, which suggests a testing-strategy problem rather than only a test-count problem.
- Modularity is not strong enough; new functionality can still break core behavior or require core changes.
- The codebase feels fragile: changing one thing can break something else unexpectedly.
- Running the test suite takes too long.
- Inference backend provider coverage is still lacking.
- The bidirectional text flow through the proxy feels overly complex and likely needs architectural simplification.
- Separate streaming and non-streaming code paths are a major maintenance burden.
- Multi-tier loop detection remains defunct, unstable, and hard to test.
- There is concern about possible data leaks across sessions or users.
- Multi-tenancy support is still missing.
- Documentation sync is getting harder as the project grows.

## Revenue-Aligned Gaps

These are important, but they should be planned on top of a more stable and secure base:

- Precise billing
- SSO-based token management
- User provisioning
- Stronger safety/protection features
- Web GUI for user/token management
- Web GUI for statistics and business-grade reporting
- Proper session logging for audit purposes with less noise
- Session logging to cloud providers or databases instead of only local files/SQLite
- Security audit and hardening

## What Should Wait

- New features focused mainly on the vibe-coding audience
- New features that are not aligned with business or commercial needs
- Optional expansion work that increases core coupling before stability and security improve

## Planning Direction

- Stabilization and security hardening come first.
- Architectural decoupling between core and non-core functionality is a top-level design goal.
- Testing strategy needs to improve in effectiveness, runtime, and provider coverage.
- Business-value features should be prioritized over novelty once the platform is stable enough to support them safely.
- Prefer simplification over feature accretion whenever both paths could solve the same problem.
- Avoid building features that no customer has asked for and no business case supports.
- The target is a stable product that businesses will pay for, so roadmap choices should favor trust, operability, and monetizable foundations.
