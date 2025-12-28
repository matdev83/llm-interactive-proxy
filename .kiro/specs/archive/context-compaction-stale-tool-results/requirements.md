# Requirements Document

## Project Description (Input)

Intelligent context compression feature: provide clients with a mechanism to dynamically remove or replace stale tool call results from the message history sent to remote LLMs. Stale tool results (for example, repeated file reads) should be compacted only when a more recent result for the same resource exists; never remove the most recent tool output. Older, superseded tool results can be summarized or replaced with stub messages that warn the content is obsolete because newer outputs are present.

Prior discussion (for context and rationale):
> Brainstormed an "intelligent payload compression" approach to cut oversized prompts (e.g., multi-MB histories). Proposed per-tool, per-resource sliding windows that keep only the latest full outputs and replace older ones with short stubs. Focus on tool results (file reads, test logs), never user/system/assistant reasoning. Consider token-budget awareness and explicit markers so the LLM knows older details were truncated. Potential location: request pipeline before backend translation (e.g., history compaction middleware), keeping connectors simple. Risks include removing needed info; mitigations include conservative rules and preserving CBOR captures of the post-compaction payload.

## Introduction

Deliver an intelligent context compaction capability that trims stale tool outputs while preserving the latest results and conversational integrity. The goal is to reduce prompt size (token and byte) without removing current evidence the model needs, while keeping the proxy transparent about any truncation performed.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:

- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### 1. Stale tool result detection and scoping

**Objective:** As an operator of the proxy, I want stale tool outputs identified precisely, so that only superseded results are compacted and current context remains intact.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1.1. When a newer tool result for the same resource (e.g., file path or command signature) is added to history, the proxy shall mark all earlier tool result messages for that resource as stale.
1.1.1. For file read operations with offset/limit parameters, the proxy shall treat each unique combination of file path, offset, and limit as a distinct resource; reads of different portions of the same file shall NOT be considered duplicates of each other.
1.2. While no newer tool result exists for a resource, the proxy shall retain the latest tool result content unmodified.
1.3. When a tool message lacks a resource identity sufficient to correlate (e.g., missing file path), the proxy shall skip compaction for that message and preserve its content.
1.4. Where the message role is user, system, or assistant reasoning, the proxy shall bypass compaction and keep the original message unchanged.
1.5. If compaction state for a resource cannot be determined, the proxy shall log the condition and leave the associated tool results unmodified.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### 2. Compaction and stub replacement behavior

**Objective:** As an operator of the proxy, I want stale tool outputs replaced with explicit stubs, so that the LLM sees that prior content was removed because newer outputs exist.

**Priority:** P0 (Critical)

#### Acceptance Criteria

2.1. When a tool result is marked stale, the proxy shall replace its content with a stub that states truncation occurred, identifies the resource, and indicates that newer outputs exist later in history.
2.2. While compacting messages, the proxy shall preserve chronological ordering and original metadata (role, tool name, call identifiers) unchanged.
2.3. When compacting repeated outputs for a resource, the proxy shall keep the most recent full tool result message intact and retain at least one stub that signals earlier executions were truncated.
2.4. Where compaction is applied, the proxy shall forward the stubbed message payload to downstream connectors in place of the original content without dropping the message.
2.5. If stub generation fails, the proxy shall revert to retaining the original tool content and emit an error log with context.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### 3. Token budget governance for compaction

**Objective:** As a proxy operator, I want compaction governed by token budget thresholds, so that oversized prompts are reduced safely before exceeding model limits.

**Priority:** P1 (High)

#### Acceptance Criteria

3.1. While estimated outbound tokens exceed a configurable compaction threshold, the proxy shall iteratively compact stale tool results until the estimate falls below the target or no further stale items remain.
3.2. When compaction cannot reduce the estimated tokens below the configured maximum, the proxy shall emit a warning indicating residual overflow risk before forwarding the request.
3.3. When compaction is disabled via configuration, the proxy shall forward history untouched and log that compaction was skipped due to configuration.
3.4. Where per-tool-type policies exist, the proxy shall apply allow/deny lists (e.g., compact only read/test outputs) before compacting any message.
3.5. If the estimated token usage is already below the compaction threshold, the proxy shall avoid modifying any tool messages.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### 4. Observability, safety, and traceability

**Objective:** As an operator, I want compaction to be observable and fail-safe, so that truncation decisions are auditable without losing operational visibility.

**Priority:** P1 (High)

#### Acceptance Criteria

4.1. When compaction occurs, the proxy shall record metrics per request capturing counts of compacted messages, bytes removed, and estimated token savings.
4.2. When a request is compacted, the proxy shall annotate logs or CBOR capture metadata with a compaction summary (without storing removed content) for replay and debugging.
4.3. Where runtime feature flags control compaction, the proxy shall apply the current flag per request and include the flag state in diagnostics.
4.4. If compaction logic errors occur, the proxy shall fail open by forwarding original content and logging the error with `exc_info=True`.
4.5. While emitting diagnostics, the proxy shall redact sensitive payload content per existing redaction rules to avoid leaking tool outputs.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

## Non-Functional Requirements

### NFR 1: Performance

- Compaction pass shall add no more than 10 ms p95 per request under typical histories (<=200 messages).
- Token estimation and compaction shall avoid blocking the event loop by using async-compatible operations.

### NFR 2: Reliability

- Compacting shall preserve message order and IDs so downstream connectors process consistent histories.
- Fail-open behavior shall ensure requests still forward even if compaction encounters errors.

### NFR 3: Observability

- Metrics shall include per-tool-type compaction counts and bytes saved.
- Logs shall capture compaction decisions at INFO and errors at ERROR with `exc_info=True`.

### NFR 4: Security

- Redaction rules shall apply to any logged snippets or stubs to avoid leaking sensitive tool outputs.
- Feature flags and configs controlling compaction shall not expose secrets in logs or responses.

## Glossary

| Term | Definition |
|------|------------|
| Stale Tool Result | A tool output that has been superseded by a newer result for the same resource within the conversation history |
| Compaction Stub | A replacement message indicating earlier tool output was truncated because newer information exists |
| Resource Identity | Attributes (e.g., file path, command signature, and optional parameters like offset/limit) used to correlate tool results referring to the same target. For partial file reads, the identity includes offset and limit to distinguish reads of different file portions. |
| Token Budget | Configurable threshold for estimated outbound tokens that triggers compaction to avoid model limits |
