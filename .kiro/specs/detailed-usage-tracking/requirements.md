# Requirements Document

## Introduction

This document specifies the requirements for a comprehensive usage tracking and statistics system for the LLM proxy. The system will provide precise analysis of all traffic passing through the proxy, enabling detailed monitoring, billing reconciliation, and performance analysis. The feature extends the existing basic usage tracking to support multi-dimensional breakdowns, persistent storage, and real-time statistics across all proxy components.

## Glossary

- **Backend Connector**: A component that communicates with remote LLM inference APIs (e.g., OpenAI, Anthropic, Gemini)
- **Frontend Connector**: A component that receives requests from client applications (e.g., OpenAI-compatible API, Anthropic API)
- **Leg**: A directional segment of traffic flow: CLIENT_TO_PROXY (CTP), PROXY_TO_CLIENT (PTC), PROXY_TO_BACKEND (PTB), BACKEND_TO_PROXY (BTP)
- **Verbatim Traffic**: Original, unmodified content as received from client or backend before any proxy mutations
- **Mutated Traffic**: Content after proxy modifications (e.g., command injection, content filtering, model replacement)
- **Proxy-Calculated Usage**: Token counts and metrics calculated by the proxy itself using tokenization
- **Backend-Reported Usage**: Token counts, costs, and billing information reported by remote LLM inference APIs
- **Session**: A logical grouping of related requests, typically identified by a session ID
- **Turn**: A single request-response cycle within a session
- **TTFT**: Time To First Token - the latency from request submission to receiving the first response token
- **TPS**: Tokens Per Session - the average number of tokens consumed per session
- **Proxy Processing Time**: The time spent by the proxy processing a request/response, excluding backend latency
- **Rolling Window**: A time-based aggregation that continuously updates as time progresses
- **Usage Record**: A single data point capturing metrics for one request-response cycle
- **Statistics Aggregation**: The process of combining multiple usage records into summary metrics

## Requirements

### Requirement 1: Token Tracking with Verbatim and Mutated Measurements

**User Story:** As a system administrator, I want to track the number of tokens at all four measurement points (verbatim ingress, mutated egress to backend, verbatim backend response, mutated egress to client), so that I can have full observability of traffic before and after proxy mutations.

#### Acceptance Criteria

1. WHEN a request is received at a frontend connector THEN the Usage_Tracking_System SHALL record verbatim_inbound_tokens BEFORE any proxy modifications
2. WHEN a request is sent to a backend connector THEN the Usage_Tracking_System SHALL record mutated_outbound_tokens AFTER all proxy modifications
3. WHEN a response is received from a backend connector THEN the Usage_Tracking_System SHALL record verbatim_backend_tokens BEFORE any proxy modifications
4. WHEN a response is sent to the client THEN the Usage_Tracking_System SHALL record mutated_response_tokens AFTER all proxy modifications
5. WHEN tokens are recorded THEN the Usage_Tracking_System SHALL associate them with the specific backend type (e.g., openai, anthropic, gemini)
6. WHEN tokens are recorded THEN the Usage_Tracking_System SHALL associate them with the effectively used model name
7. WHEN the proxy modifies content THEN the Usage_Tracking_System SHALL store BOTH verbatim and mutated token counts as separate fields for comparison

### Requirement 2: Request and Response Tracking

**User Story:** As a system administrator, I want to track the number of requests and responses, so that I can monitor system throughput and identify issues.

#### Acceptance Criteria

1. WHEN a request is received by the proxy THEN the Usage_Tracking_System SHALL increment the request counter for the appropriate frontend
2. WHEN a response is sent to the client THEN the Usage_Tracking_System SHALL increment the response counter and record the HTTP status code
3. WHEN a request is forwarded to a backend THEN the Usage_Tracking_System SHALL record the backend request with its associated backend type and model
4. WHEN a response is received from a backend THEN the Usage_Tracking_System SHALL record the backend response with its HTTP status code
5. IF a request fails before reaching a backend THEN the Usage_Tracking_System SHALL record the failure with an appropriate error category

### Requirement 3: Tool Call Tracking

**User Story:** As a developer, I want to track tool calls made during LLM interactions, so that I can analyze tool usage patterns.

#### Acceptance Criteria

1. WHEN a response contains tool calls THEN the Usage_Tracking_System SHALL count and record the number of tool calls
2. WHEN tool calls are recorded THEN the Usage_Tracking_System SHALL associate them with the session, backend, and model
3. WHEN tool calls are recorded THEN the Usage_Tracking_System SHALL capture the tool names used
4. WHEN aggregating statistics THEN the Usage_Tracking_System SHALL provide tool call counts per session, backend, and model

### Requirement 4: Session Tracking

**User Story:** As a system administrator, I want to track unique sessions and turns per session, so that I can understand usage patterns.

#### Acceptance Criteria

1. WHEN a new session ID is encountered THEN the Usage_Tracking_System SHALL register it as a unique session
2. WHEN a request is processed within a session THEN the Usage_Tracking_System SHALL increment the turn counter for that session
3. WHEN aggregating statistics THEN the Usage_Tracking_System SHALL calculate tokens per session (TPS) as total_tokens divided by session_count
4. WHEN a session is inactive for a configurable period THEN the Usage_Tracking_System SHALL mark it as completed for statistics purposes

### Requirement 5: Timing and Throughput Metrics

**User Story:** As a performance engineer, I want to track timing and throughput metrics, so that I can identify performance bottlenecks and measure system capacity.

#### Acceptance Criteria

1. WHEN a streaming response begins THEN the Usage_Tracking_System SHALL record the time to first token (TTFT) as the duration from request receipt to first token emission
2. WHEN a request is processed THEN the Usage_Tracking_System SHALL record the proxy processing time excluding backend latency
3. WHEN a request completes THEN the Usage_Tracking_System SHALL record the total request duration
4. WHEN aggregating timing metrics THEN the Usage_Tracking_System SHALL calculate min, max, average, and percentile values (p50, p95, p99)
5. WHEN aggregating statistics for a time window THEN the Usage_Tracking_System SHALL calculate tokens per second (TPS) as completion_tokens divided by time_window_seconds
6. WHEN tracking TTFT THEN the Usage_Tracking_System SHALL record TTFT for all requests (streaming and non-streaming) where first token timing is measurable

### Requirement 6: HTTP Status Code Tracking

**User Story:** As a system administrator, I want to track HTTP status codes from backend APIs, so that I can monitor error rates and API health.

#### Acceptance Criteria

1. WHEN a response is received from a backend THEN the Usage_Tracking_System SHALL record the HTTP status code
2. WHEN recording status codes THEN the Usage_Tracking_System SHALL associate them with the backend type and model
3. WHEN aggregating status codes THEN the Usage_Tracking_System SHALL provide breakdowns by backend, model, and time window
4. WHEN status codes are tracked THEN the Usage_Tracking_System SHALL maintain rolling time window aggregations (1 minute, 5 minutes, 1 hour)

### Requirement 7: Multi-Dimensional Breakdowns

**User Story:** As an analyst, I want to view usage statistics with multiple breakdown dimensions, so that I can perform detailed analysis.

#### Acceptance Criteria

1. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by backend type
2. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by effectively used model
3. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by frontend type
4. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by traffic leg (CTP, PTC, PTB, BTP)
5. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by user-agent or application title
6. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by proxy user
7. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by date dimensions (day of week, day of month, week, month, year)
8. WHEN querying statistics THEN the Usage_Tracking_System SHALL support filtering by time dimension (hour of day)
9. WHEN querying statistics THEN the Usage_Tracking_System SHALL support combining multiple filter dimensions

### Requirement 8: Backend-Reported Usage Tracking (Separate from Proxy Calculations)

**User Story:** As a billing administrator, I want to capture and store ALL usage/billing information reported by remote LLM backends (per OpenRouter API format) SEPARATELY from our proxy-calculated values, so that I can reconcile our calculations with provider billing and identify discrepancies.

#### Acceptance Criteria

1. WHEN a backend response includes usage metadata THEN the Usage_Tracking_System SHALL extract and store ALL backend-reported fields: prompt_tokens, completion_tokens, total_tokens
2. WHEN a backend response includes extended token details THEN the Usage_Tracking_System SHALL extract and store: reasoning_tokens (for thinking models), cached_tokens (for cached prompts), audio_tokens (for audio input)
3. WHEN a backend response includes cost information THEN the Usage_Tracking_System SHALL extract and store: cost (USD per request), upstream_inference_cost (for BYOK requests)
4. WHEN storing usage data THEN the Usage_Tracking_System SHALL maintain THREE separate categories of token counts: (a) proxy-calculated verbatim, (b) proxy-calculated mutated, (c) backend-reported (as complete OpenRouterUsage object)
5. WHEN querying usage THEN the Usage_Tracking_System SHALL provide all three categories of values for comparison and reconciliation
6. WHEN aggregating statistics THEN the Usage_Tracking_System SHALL support aggregation by each category separately (proxy-calculated vs backend-reported)

### Requirement 9: In-Memory Storage with Periodic Persistence

**User Story:** As a system administrator, I want usage data to be stored in memory for fast access and periodically persisted to disk, so that I can have both high performance and durability.

#### Acceptance Criteria

1. WHEN usage data is recorded THEN the Usage_Tracking_System SHALL store it in a thread-safe in-memory data structure
2. WHEN the in-memory store has been modified THEN the Usage_Tracking_System SHALL mark it as dirty for persistence
3. WHEN the configurable flush interval elapses and the store is dirty THEN the Usage_Tracking_System SHALL persist the data to disk
4. WHEN the proxy starts THEN the Usage_Tracking_System SHALL load previously persisted data from disk
5. WHEN multiple threads access the store concurrently THEN the Usage_Tracking_System SHALL ensure thread-safe access without data corruption
6. WHEN querying historical data THEN the Usage_Tracking_System SHALL support date range filtering
7. WHEN storage grows beyond configured limits THEN the Usage_Tracking_System SHALL implement data retention policies (archival or deletion of old records)

### Requirement 10: Usage Data Serialization

**User Story:** As a developer, I want usage data to be serializable, so that I can export and import data for analysis and backup.

#### Acceptance Criteria

1. WHEN exporting usage data THEN the Usage_Tracking_System SHALL serialize records to JSON format
2. WHEN importing usage data THEN the Usage_Tracking_System SHALL deserialize JSON records and validate their structure
3. WHEN serializing usage data THEN the Usage_Tracking_System SHALL include all tracked dimensions and metrics
4. WHEN deserializing usage data THEN the Usage_Tracking_System SHALL produce equivalent objects to the original data (round-trip consistency)

### Requirement 11: Real-Time Statistics API

**User Story:** As a monitoring system, I want to query real-time statistics via an API, so that I can display dashboards and alerts.

#### Acceptance Criteria

1. WHEN the statistics API is queried THEN the Usage_Tracking_System SHALL return current aggregated metrics within 1 second
2. WHEN the statistics API is queried with filters THEN the Usage_Tracking_System SHALL apply the requested breakdown dimensions
3. WHEN the statistics API is queried THEN the Usage_Tracking_System SHALL include both cumulative and rolling window statistics
4. IF the statistics API receives invalid filter parameters THEN the Usage_Tracking_System SHALL return a descriptive error message

