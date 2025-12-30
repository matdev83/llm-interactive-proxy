# Requirements Document

## Introduction
This specification refines and hardens the existing history compaction behavior that replaces stale tool results with explicit stubs to reduce oversized prompts, with a focus on correctness for paginated file reads and safety/observability in agentic workflows.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Project Description (Input)
history-compaction-follow-up

## Requirements

### Requirement 1: Resource Identity Correctness for Tool Results
**Objective:** As an operator, I want the proxy to identify tool results by a precise and stable resource identity, so that only truly superseded outputs are compacted.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1. The LLM Interactive Proxy shall determine a resource identity for each tool result message based on the tool name and the tool call parameters that materially affect the tool output.
1.2. When tool call parameters are semantically equivalent but encoded differently (for example, JSON string vs object, or numeric strings vs integers), the LLM Interactive Proxy shall produce the same resource identity.
1.3. When a tool reads a file with selection parameters (for example, `offset`, `limit`, `start_line`, `end_line`, `index`, `page`, `cursor`, `chunk_size`, or `length`), the LLM Interactive Proxy shall treat each unique combination of file path and selection parameters as a distinct resource identity.
1.4. When two tool results refer to the same file path but different selection parameters, the LLM Interactive Proxy shall not mark either result as stale due to the other.
1.5. When a tool result message lacks a resource identity sufficient to correlate (for example, missing file path or unreadable tool parameters), the LLM Interactive Proxy shall preserve the message content unchanged.
1.6. If the LLM Interactive Proxy cannot determine whether two tool results refer to the same resource identity, the LLM Interactive Proxy shall preserve both message contents unchanged and shall record diagnostics indicating the ambiguity.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 2: Staleness Detection and Preservation Invariants
**Objective:** As an operator, I want only stale tool outputs compacted and the latest results preserved, so that the model retains current evidence and the conversation remains coherent.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1. When a newer tool result is present in the history for the same resource identity, the LLM Interactive Proxy shall mark older tool result messages for that same resource identity as stale.
2.2. While no newer tool result exists for a resource identity, the LLM Interactive Proxy shall retain the most recent tool result content for that resource identity unmodified.
2.3. The LLM Interactive Proxy shall not compact user, system, or assistant messages (including assistant reasoning content).
2.4. When compacting messages, the LLM Interactive Proxy shall preserve message order and shall preserve tool call identifiers and tool metadata required for downstream connector compatibility.
2.5. When the LLM Interactive Proxy processes a history that already contains compaction stubs, the LLM Interactive Proxy shall not modify those stubbed messages further.
2.6. When a history contains compaction stubs without message metadata (for example, a client re-submits the history), the LLM Interactive Proxy shall still recognize those messages as compaction stubs and shall not compact them again.
2.7. Where preservation limits are configured, the LLM Interactive Proxy shall preserve at least the configured number of most recent tool results per resource identity unmodified.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 3: Stub Transparency for Agentic Workflows
**Objective:** As an operator, I want compacted outputs replaced with transparent stubs that preserve actionable context, so that the LLM can reason correctly about what was removed and where newer information exists.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1. When a tool result is compacted, the LLM Interactive Proxy shall replace the tool result content with an explicit stub indicating that prior output was removed because newer output exists later in the conversation.
3.2. When a tool result is compacted, the LLM Interactive Proxy shall include in the stub sufficient resource identity information to distinguish the compacted result from other results for the same primary resource (for example, include selection parameters for paginated file reads).
3.3. When a compacted tool result includes selection parameters, the LLM Interactive Proxy shall include those selection parameter names and values in the stub.
3.4. When compaction is applied for a resource identity, the LLM Interactive Proxy shall retain at least one stub message indicating that earlier executions were compacted and shall preserve the latest full tool result message for that resource identity.
3.5. If stub generation fails for any reason, the LLM Interactive Proxy shall preserve the original tool result content unchanged and shall record diagnostics for the failure.
3.6. The LLM Interactive Proxy shall generate compaction stubs in a form that is unambiguously recognizable as a stub in later processing, including when message metadata is absent.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 4: Token Budget Governance and Threshold Semantics
**Objective:** As an operator, I want compaction governed by explicit token budget thresholds with predictable boundary behavior, so that oversized prompts are reduced safely and consistently.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1. When the estimated outbound tokens are greater than or equal to the configured compaction threshold, the LLM Interactive Proxy shall be permitted to compact eligible stale tool results.
4.2. When the estimated outbound tokens are below the configured compaction threshold, the LLM Interactive Proxy shall forward the history without modifying any tool messages.
4.3. While the estimated outbound tokens remain greater than or equal to the configured compaction threshold and eligible stale tool results remain available, the LLM Interactive Proxy shall compact additional eligible stale tool results, subject to configured preservation limits.
4.4. If compaction cannot reduce the estimated outbound tokens below the configured maximum token budget, the LLM Interactive Proxy shall emit a warning indicating residual overflow risk and shall forward the request.
4.5. When compaction is disabled by configuration, the LLM Interactive Proxy shall forward the history untouched and shall record that compaction was skipped due to configuration.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 5: Safety-First Eligibility Policies and Defaults
**Objective:** As an operator, I want conservative default eligibility policies for compaction with explicit opt-in for risky tool outputs, so that compaction does not remove critical evidence or amplify mistakes.

**Priority:** P1 (High)

#### Acceptance Criteria
5.1. Where compaction is enabled, the LLM Interactive Proxy shall apply eligibility policies that allow compaction only for explicitly permitted tool result types.
5.2. When no tool types are explicitly permitted by policy, the LLM Interactive Proxy shall preserve all tool result content unmodified.
5.3. When a tool result type is not recognized or is not explicitly permitted by policy, the LLM Interactive Proxy shall preserve that tool result content unmodified.
5.4. When a tool result type is explicitly denied by policy, the LLM Interactive Proxy shall preserve that tool result content unmodified even if it is stale.
5.5. The LLM Interactive Proxy shall allow operators to configure eligibility policies at least by tool type/category and by tool name.
5.6. Where policies change between requests, the LLM Interactive Proxy shall apply the current policies per request without relying on previously cached compaction decisions.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 6: Observability, Redaction, and Accounting Correctness
**Objective:** As an operator, I want compaction to be observable and safe to operate in production, so that compaction decisions are auditable without leaking sensitive tool outputs.

**Priority:** P1 (High)

#### Acceptance Criteria
6.1. When compaction occurs, the LLM Interactive Proxy shall record diagnostics including the number of compacted messages, an estimate of bytes removed, and an estimate of token savings.
6.2. When compaction occurs, the LLM Interactive Proxy shall not persist or emit the removed tool output content as part of compaction diagnostics.
6.3. Where resource identifier redaction is enabled, the LLM Interactive Proxy shall redact resource identifiers in compaction stubs and in compaction diagnostics such that unredacted file paths and full command strings are not emitted.
6.4. If the proxy’s compaction savings estimates would be negative due to stub overhead, the LLM Interactive Proxy shall report zero savings for those estimates.
6.5. If compaction logic encounters an error, the LLM Interactive Proxy shall fail open by forwarding the original history and shall record diagnostics including the error condition.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 7: Extensibility for Additional Tool Result Types
**Objective:** As an operator, I want the proxy to support safe compaction for multiple tool result types beyond file reads, so that oversized histories from common agent tools can be reduced predictably.

**Priority:** P2 (Medium)

#### Acceptance Criteria
7.1. When a tool result type has a defined resource identity and is permitted by policy, the LLM Interactive Proxy shall apply stale-result compaction for that tool result type.
7.2. When a tool result type produces outputs scoped by a query and a target scope (for example, search tools), the LLM Interactive Proxy shall treat the resource identity as a combination of query and scope parameters.
7.3. When a tool result type produces outputs scoped by a directory and filters (for example, directory listing tools), the LLM Interactive Proxy shall treat the resource identity as a combination of directory and filter parameters.
7.4. When a tool result type produces outputs that are not safely correlatable to a resource identity, the LLM Interactive Proxy shall preserve those outputs unchanged.
7.5. When a tool result type includes both query parameters and scope parameters, the LLM Interactive Proxy shall not use scope parameters alone as the query component of the resource identity.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

## Non-Functional Requirements

### NFR 1: Performance
- The LLM Interactive Proxy shall complete compaction evaluation and transformation within 10 ms p95 for typical histories (≤200 messages) on supported deployment targets.
- The LLM Interactive Proxy shall avoid blocking the event loop during compaction processing.

### NFR 2: Reliability
- The LLM Interactive Proxy shall preserve message ordering in all compaction outcomes.
- The LLM Interactive Proxy shall fail open on compaction errors and shall continue request processing.

### NFR 3: Observability
- The LLM Interactive Proxy shall provide metrics and structured logs sufficient to determine whether compaction occurred, what policies were active, and whether compaction failed open.

### NFR 4: Security
- Where resource identifier redaction is enabled, the LLM Interactive Proxy shall avoid emitting unredacted resource identifiers in compaction-related outputs.
- The LLM Interactive Proxy shall not include removed tool output content in compaction diagnostics.

## Glossary
| Term | Definition |
|------|------------|
| Tool Result Message | A message representing a tool output returned to the LLM in chat history |
| Resource Identity | A stable identifier used to correlate tool outputs that refer to the same underlying resource and selection parameters |
| Selection Parameters | Parameters (for example, offset/limit/index/page) that determine which portion of a resource is returned by a tool |
| Stale Tool Result | A tool output superseded by a newer tool output for the same resource identity |
| Compaction Stub | A replacement message indicating earlier tool output was removed because newer information exists |
