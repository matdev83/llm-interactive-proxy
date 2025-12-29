# Requirements Document

## Introduction
This specification defines a robust way to tag and filter messages that must not be forwarded from client-submitted history through the proxy to remote LLM backends, even if clients re-submit full conversation history. It covers (a) messages that must never reach a backend (for example slash commands and server-generated command responses) and (b) server-injected steering/internal messages that may be sent when injected by the proxy but must be excluded if later echoed by clients or agent frameworks.

This is an alpha-stage project. Backward compatibility with legacy or deprecated behavior is not required; the feature is expected to be implemented as the single final mechanism, without fallbacks to legacy code paths.

The proxy may optionally compact/compress historical tool call results before backend dispatch. Non-forwardable tagging must remain effective even when such server-side history compaction rewrites message content.

**Discovered Constraints (from Gap Analysis)**:
- Current “do not forward” behavior relies on regex- and metadata-based mechanisms that do not survive client history re-submission; this spec replaces them with session-scoped tagging and a single enforcement boundary.
- Some entry points can currently bypass the centralized backend call flow; enforcement must therefore live at the single backend-call boundary used by all entry points.
- The command pipeline may modify message content during command handling; tagging must still recognize the original client-submitted message when it later appears in client history.
- Not all non-HTTP workflows reliably establish a session id today; this spec requires a session identifier be resolved or created for every interaction that may call a remote backend.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Session-Scoped Non-Forwardable Tagging
**Objective:** As an operator, I want non-forwardable messages to be tracked per session, so that internal-only messages are never forwarded from client-submitted history to remote backends even when clients resend history.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 The LLM Interactive Proxy shall support tagging individual messages in a session as non-forwardable under a defined forwarding scope.
1.2 The LLM Interactive Proxy shall derive a deterministic message identity for purposes of recognizing previously tagged non-forwardable messages within the same session.
1.3 When a message is tagged as non-forwardable in a session, the LLM Interactive Proxy shall treat that tag as immutable for the lifetime of that session.
1.4 When a client submits conversation history that includes a message previously tagged as non-forwardable in the same session, the LLM Interactive Proxy shall recognize that message as non-forwardable based on its message identity and shall exclude it from any outbound backend payload.
1.5 When non-forwardable messages are excluded from an outbound backend payload, the LLM Interactive Proxy shall preserve the relative order of remaining forwardable messages.
1.6 While filtering non-forwardable messages from an outbound backend payload, the LLM Interactive Proxy shall not modify the content of remaining forwardable messages.
1.7 The LLM Interactive Proxy shall support a “never-forward” scope in which a tagged message is excluded from all outbound backend payloads for the lifetime of the session.
1.8 The LLM Interactive Proxy shall support a “client-history-only” scope in which a tagged message is excluded only when it appears in client-submitted history, but may be included when injected by the proxy for a backend-call workflow.
1.9 When computing message identity, the LLM Interactive Proxy shall use only canonical message attributes and shall not depend on client-provided metadata or transport-specific fields that may not round-trip through clients.
1.10 When two messages are semantically equivalent after the proxy’s canonical request normalization, the LLM Interactive Proxy shall compute the same message identity for both.
1.11 When a message is tagged in the “never-forward” scope, the LLM Interactive Proxy shall exclude it from any outbound backend payload regardless of whether it originated from the client or from the proxy.
1.12 When the LLM Interactive Proxy compacts or compresses historical tool call results for a request, the LLM Interactive Proxy shall preserve non-forwardable tag recognition for the compacted messages within the same session.
1.13 When a message’s content is rewritten by a server-side history compaction feature, the LLM Interactive Proxy shall ensure the message identity used for non-forwardable matching remains stable for that message within the same session.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 2: Client Slash Commands Are Never Forwarded
**Objective:** As a client user, I want slash commands to be handled by the server, so that commands do not reach remote LLM backends.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 When the client submits a message that is identified as a slash command, the LLM Interactive Proxy shall not forward that message to any remote LLM backend.
2.2 When the client submits a message that begins with the configured command prefix (default `!/`), the LLM Interactive Proxy shall treat the message as a slash command candidate.
2.3 When a slash command candidate is valid and supported, the LLM Interactive Proxy shall execute the command server-side and shall return a command response to the client without calling any remote LLM backend.
2.4 If a slash command candidate is not valid or not supported, then the LLM Interactive Proxy shall return an error response to the client and shall not call any remote LLM backend.
2.5 When a slash command is handled server-side, the LLM Interactive Proxy shall tag the slash command message (as submitted by the client) as non-forwardable in the “never-forward” scope for the lifetime of the session.

#### Technical Constraints
- The LLM Interactive Proxy shall apply this behavior consistently across supported frontends that accept client-provided message content and history.

### Requirement 3: Command Responses Are Never Forwarded
**Objective:** As an operator, I want server-generated responses to commands to never be forwarded, so that internal command output cannot leak into remote backend prompts via client history re-submission.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 When the LLM Interactive Proxy generates a response message to a slash command and sends it to the client, the LLM Interactive Proxy shall tag that response message (as sent to the client) as non-forwardable in the “never-forward” scope for the lifetime of the session.
3.2 When a client submits conversation history containing a previously generated command response message from the same session, the LLM Interactive Proxy shall recognize it as non-forwardable and shall exclude it from any outbound backend payload.
3.3 While processing a request that includes a previously generated command response message, the LLM Interactive Proxy shall not require the client to preserve any special out-of-band metadata for the message to be recognized within the same session.

#### Technical Constraints
- The LLM Interactive Proxy shall maintain behavior for both streaming and non-streaming client interactions where applicable.

### Requirement 4: Server-Managed Steering Messages Are Not Client-Forwardable
**Objective:** As a developer, I want server-managed steering/internal messages to be protected from being re-forwarded by clients, so that client-managed history cannot inadvertently duplicate or leak internal prompt steering.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1 When the LLM Interactive Proxy injects a server-managed steering/internal message as part of a backend request workflow, the LLM Interactive Proxy shall record that message in the session as non-forwardable in the “client-history-only” scope.
4.2 When a client submits conversation history containing a server-managed steering/internal message previously used in the same session, the LLM Interactive Proxy shall exclude that message from any outbound backend payload.
4.3 If a client submits message metadata that attempts to mark a message as non-forwardable, then the LLM Interactive Proxy shall ignore the client-provided marking unless the message is recognized as server-tagged within the session.
4.4 When the LLM Interactive Proxy injects a server-managed steering/internal message for a backend call, the LLM Interactive Proxy shall include that injected message in the outbound backend payload for that call.

#### Technical Constraints
- The LLM Interactive Proxy shall not expose internal-only tagging mechanisms as a required client integration dependency.

### Requirement 5: Filtering Works Across Supported Protocols and Roles
**Objective:** As a developer, I want non-forwardable filtering to be consistent across APIs, so that behavior is predictable regardless of which frontend protocol is used.

**Priority:** P0 (Critical)

#### Acceptance Criteria
5.1 Where a supported frontend request includes a message history, the LLM Interactive Proxy shall apply non-forwardable filtering before sending content to any remote LLM backend.
5.2 When filtering is applied, the LLM Interactive Proxy shall support filtering messages across all roles/content types that the frontend protocol can carry (for example user, assistant, system, and tool-related messages).
5.3 If filtering removes all forwardable user-provided content from a request, then the LLM Interactive Proxy shall not call any remote LLM backend and shall return an error response indicating that there is nothing forwardable to send.
5.4 When filtering removes one or more messages, the LLM Interactive Proxy shall still produce a valid backend request structure for the selected backend protocol.

#### Technical Constraints
- The LLM Interactive Proxy shall not increase the number of backend calls for a request due to filtering.

### Requirement 6: Observability of Filtering Decisions
**Objective:** As an operator, I want clear observability of filtering decisions, so that I can diagnose prompt-content issues and verify that internal messages are not being forwarded.

**Priority:** P2 (Medium)

#### Acceptance Criteria
6.1 When the LLM Interactive Proxy filters one or more messages from an outbound backend payload, the LLM Interactive Proxy shall emit a structured log entry that includes the request correlation identifier and the number of messages filtered.
6.2 While emitting logs about filtered messages, the LLM Interactive Proxy shall avoid logging sensitive message contents by default.
6.3 When wire capture is enabled, the LLM Interactive Proxy shall ensure the captured outbound payload sent to the remote LLM backend excludes non-forwardable messages.

#### Technical Constraints
- Logging shall follow the project’s structured logging approach.

### Requirement 7: Single Enforcement Point for All Backend Calls (Option B)
**Objective:** As an operator, I want a single authoritative enforcement point for non-forwardable filtering, so that filtering is applied consistently across all code paths that can call remote LLM backends.

**Priority:** P0 (Critical)

#### Acceptance Criteria
7.1 When the LLM Interactive Proxy is about to call any remote LLM backend, the LLM Interactive Proxy shall apply non-forwardable filtering immediately before the backend call.
7.2 When the LLM Interactive Proxy performs a backend call as part of an internal workflow (for example retries or tool-call steering), the LLM Interactive Proxy shall apply the same non-forwardable filtering as for normal client requests.
7.3 If the LLM Interactive Proxy cannot determine whether a client-submitted message matches a previously tagged non-forwardable message for the current session, then the LLM Interactive Proxy shall fail the request without calling any remote backend.
7.4 When the LLM Interactive Proxy applies optional history compaction for a request, the LLM Interactive Proxy shall still apply non-forwardable filtering on the resulting message list immediately before any backend call.
7.5 When the LLM Interactive Proxy initiates backend calls from any supported entry point (including HTTP APIs, WebSocket-based features, and internal multi-phase backend workflows), the LLM Interactive Proxy shall apply the same non-forwardable filtering behavior.
7.6 The LLM Interactive Proxy shall not perform any remote LLM backend call without invoking the non-forwardable enforcement logic.

### Requirement 8: Session Identity Coverage Across Entry Points
**Objective:** As an operator, I want consistent session identity handling across entry points, so that non-forwardable tags remain session-scoped and do not leak between different client interactions.

**Priority:** P0 (Critical)

#### Acceptance Criteria
8.1 When the LLM Interactive Proxy processes any request or workflow that may call a remote LLM backend, the LLM Interactive Proxy shall resolve or create a non-empty session identifier for that interaction.
8.2 When a non-HTTP entry point initiates multiple backend calls as part of a single logical interaction, the LLM Interactive Proxy shall reuse the same session identifier across those calls for the lifetime of that interaction.
8.3 The LLM Interactive Proxy shall store and apply non-forwardable tags only within the resolved session identifier.
8.4 The LLM Interactive Proxy shall not apply non-forwardable tags across different session identifiers.

## Non-Functional Requirements

### Requirement 9: Performance
**Objective:** As an operator, I want non-forwardable filtering to have minimal performance impact, so that proxy latency and throughput remain acceptable.

**Priority:** P1 (High)

#### Acceptance Criteria
9.1 While processing requests that include message history, the LLM Interactive Proxy shall perform non-forwardable filtering without a material increase in end-to-end request latency under normal operating conditions.

### Requirement 10: Reliability
**Objective:** As an operator, I want the proxy to fail closed on non-forwardable enforcement errors, so that internal-only messages are never leaked to remote backends.

**Priority:** P0 (Critical)

#### Acceptance Criteria
10.1 If the LLM Interactive Proxy encounters an internal error while determining whether any message is non-forwardable for the current session, then the LLM Interactive Proxy shall fail the request without calling a remote backend.

### Requirement 11: Observability
**Objective:** As an operator, I want visibility into filtering decisions, so that I can diagnose prompt-content and enforcement behavior.

**Priority:** P2 (Medium)

#### Acceptance Criteria
11.1 The LLM Interactive Proxy shall provide sufficient structured telemetry to correlate a client request with its filtered outbound backend payload.

### Requirement 12: Security
**Objective:** As an operator, I want the proxy to prevent client spoofing of non-forwardable tags, so that only server-tagged messages are treated as non-forwardable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
12.1 If a client attempts to spoof or forge server-managed message identity within a session, then the LLM Interactive Proxy shall not treat the spoofed message as server-tagged unless it is recognized as such by the proxy.

### Requirement 13: Alpha Finality and Legacy Removal
**Objective:** As a maintainer, I want this feature to fully replace legacy regex-based filtering, so that enforcement is robust and consistent with alpha-stage finality.

**Priority:** P0 (Critical)

#### Acceptance Criteria
13.1 The LLM Interactive Proxy shall not rely on regular-expression-based mechanisms to identify, strip, or sanitize non-forwardable messages.
13.2 The LLM Interactive Proxy shall not include any fallback behavior intended to preserve legacy non-forwardable filtering semantics.
13.3 Where legacy regex-based non-forwardable filtering mechanisms exist in the codebase, the LLM Interactive Proxy shall remove them and shall remove all wiring that activates them.

### Requirement 14: Bounded Tag Storage (Memory Safety)
**Objective:** As an operator, I want non-forwardable tagging to use bounded memory, so that a single long-running session cannot cause unbounded in-process memory growth.

**Priority:** P0 (Critical)

#### Acceptance Criteria
14.1 The LLM Interactive Proxy shall store non-forwardable tag state in a bounded-memory representation that does not scale with message content size (for example fixed-size identity digests and compact tag records).
14.2 The LLM Interactive Proxy shall deduplicate non-forwardable tag entries within a session such that repeated tagging of the same message identity and scope does not increase stored state.
14.3 The LLM Interactive Proxy shall enforce a configurable maximum number of stored non-forwardable identities per session; if the limit would be exceeded, the LLM Interactive Proxy shall fail the request without calling any remote backend and shall return an error response indicating that non-forwardable tag capacity has been exceeded.
14.4 The LLM Interactive Proxy shall provide a default maximum of 10,000 stored non-forwardable identities per session when not explicitly configured.

## Glossary
| Term | Definition |
|------|------------|
| Session | A logical conversation context tracked by the proxy for the duration of a client interaction. |
| Non-forwardable tag | A session-scoped classification applied by the proxy that determines when a message must be excluded from outbound backend payloads. |
| Never-forward scope | A non-forwardable scope in which a tagged message is excluded from all outbound backend payloads (regardless of origin). |
| Client-history-only scope | A non-forwardable scope in which a tagged message is excluded only when present in client-submitted history, but may be included when injected by the proxy for a backend-call workflow. |
| Message identity | A deterministic identifier derived by the proxy to recognize a previously seen message within the same session, independent of client-provided metadata. |
| Slash command | A client-submitted command (for example beginning with `!/`) that is handled server-side. |
| Command response | A server-generated response message produced as the result of handling a slash command. |
| Steering/internal message | A server-managed message used to influence backend behavior as part of proxy workflows (for example safety, tool-call UX, or steering). |
| History compaction | An optional proxy feature that rewrites historical tool call result messages (for example replacing stale outputs with explicit stubs) to reduce prompt size prior to backend dispatch. |
| Remote LLM backend | An external provider connector target (OpenAI, Anthropic, Gemini, etc.) that receives outbound requests from the proxy. |
