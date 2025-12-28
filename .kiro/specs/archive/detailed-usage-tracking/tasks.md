# Implementation Plan

- [x] 1. Create domain models and enums







  - [x] 1.1 Create TrafficLeg enum in src/core/domain/traffic_leg.py
    - Define CTP, PTB, BTP, PTC enum values
    - _Requirements: 7.4_
  - [x] 1.2 Create UsageRecord dataclass in src/core/domain/usage_record.py

    - Include all fields: id, timestamp, session_id, turn_number, backend_type, model, frontend_type, leg
    - Include verbatim token counts: verbatim_prompt_tokens, verbatim_completion_tokens (before proxy mutations)
    - Include mutated token counts: mutated_prompt_tokens, mutated_completion_tokens (after proxy mutations)
    - Include backend_reported_usage field as OpenRouterUsage (captures all OpenRouter fields: reasoning_tokens, cached_tokens, audio_tokens, cost, upstream_inference_cost)
    - Include timing metrics, tool call data, context fields
    - Add to_dict() and from_dict() methods for serialization
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 8.1, 8.2, 8.3, 10.1, 10.3_
  - [x] 1.3 Write property test for verbatim token recording at ingress points


    - **Property 1: Verbatim Token Recording at Ingress Points**
    - **Validates: Requirements 1.1, 1.3**
  - [x] 1.4 Write property test for mutated token recording at egress points


    - **Property 2: Mutated Token Recording at Egress Points**
    - **Validates: Requirements 1.2, 1.4**
  - [x] 1.5 Write property test for UsageRecord serialization round-trip


    - **Property 18: Serialization Round-Trip Consistency**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
  - [x] 1.6 Create TimingStats dataclass in src/core/domain/timing_stats.py


    - Include count, min_ms, max_ms, avg_ms, p50_ms, p95_ms, p99_ms
    - Add from_values() class method for calculation
    - _Requirements: 5.4_
  - [x] 1.7 Write property test for TimingStats calculation


    - **Property 12: Timing Statistics Correctness**
    - **Validates: Requirements 5.4**
  - [x] 1.8 Create AggregatedStats dataclass in src/core/domain/aggregated_stats.py


    - Include all count, token, throughput, timing, and status code fields
    - _Requirements: 4.3, 5.5, 6.3_
  - [x] 1.9 Create StatisticsFilter dataclass in src/core/domain/statistics_filter.py


    - Include all filter dimensions: backend_type, model, frontend_type, leg, user_agent, proxy_user, date/time filters
    - Add matches() method to check if a UsageRecord matches the filter
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_
  - [x] 1.10 Write property test for StatisticsFilter matching


    - **Property 15: Filter Correctness**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9**
-

- [x] 2. Checkpoint - Make sure all tests are passing



  - Ensure all tests pass, ask the user if questions arise.

-

- [x] 3. Implement thread-safe in-memory storage


  - [x] 3.1 Create InMemoryUsageStore class in src/core/services/in_memory_usage_store.py


    - Implement thread-safe storage using threading.RLock
    - Add add_record(), get_records(), update_record() methods
    - Include dirty flag tracking
    - _Requirements: 9.1, 9.5_
  - [x] 3.2 Write property test for thread-safe concurrent access


    - **Property 20: Thread-Safe Concurrent Access**
    - **Validates: Requirements 9.1, 9.5**
  - [x] 3.3 Implement periodic persistence mechanism

    - Add flush_to_disk() and load_from_disk() methods
    - Implement background flush thread with configurable interval
    - Add shutdown handling for graceful persistence
    - _Requirements: 9.2, 9.3, 9.4_
  - [x] 3.4 Write property test for persistence dirty flag

    - **Property 21: Persistence Dirty Flag Correctness**
    - **Validates: Requirements 9.2, 9.3**
  - [x] 3.5 Implement JSON serialization for persistence

    - Create persistence format with version, timestamp, records, sessions

    - Handle file I/O errors gracefully
    - _Requirements: 10.1, 10.2_

-

- [x] 4. Checkpoint - Make sure all tests are passing



  - Ensure all tests pass, ask the user if questions arise.
-

- [x] 5. Implement usage recording service



  - [x] 5.1 Create IUsageRecordingService interface in src/core/interfaces/usage_recording_interface.py


    - Define record_request() and record_response() method signatures
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [x] 5.2 Implement UsageRecordingService in src/core/services/usage_recording_service.py


    - Implement record_request() to create UsageRecord with request data
    - Implement record_response() to complete UsageRecord with response data
    - Include timing measurement (TTFT, proxy processing, total duration)
    - Extract tool call information from responses
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 3.3, 5.1, 5.2, 5.3_
  - [x] 5.3 Write property test for token association correctness


    - **Property 3: Token Association Correctness**
    - **Validates: Requirements 1.5, 1.6**
  - [x] 5.4 Write property test for tool call count accuracy

    - **Property 5: Tool Call Count Accuracy**
    - **Validates: Requirements 3.1, 3.2, 3.3**
  - [x] 5.5 Write property test for timing metrics validity

    - **Property 11: Timing Metrics Validity**
    - **Validates: Requirements 5.1, 5.2, 5.3**
  - [x] 5.6 Implement backend-reported usage extraction

    - Extract ALL usage metadata from backend responses using OpenRouterUsage.from_dict()
    - Capture: prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens, audio_tokens, cost, upstream_inference_cost
    - Store complete OpenRouterUsage object in backend_reported_usage field
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 5.7 Write property test for backend-reported usage preservation


    - **Property 16: Backend-Reported Usage Separation**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
-

- [ ] 6. Checkpoint - Make sure all tests are passing

  - Ensure all tests pass, ask the user if questions arise.
-

- [x] 7. Implement statistics aggregation service



  - [x] 7.1 Create IStatisticsService interface in src/core/interfaces/statistics_service_interface.py


    - Define get_aggregated_stats(), get_rolling_window_stats(), get_status_code_breakdown() signatures
    - _Requirements: 6.3, 7.1-7.9, 11.2, 11.3_
  - [x] 7.2 Implement StatisticsAggregationService in src/core/services/statistics_aggregation_service.py


    - Implement aggregation logic for all metrics
    - Calculate tokens_per_session, completion_tokens_per_second, total_tokens_per_second
    - Calculate timing statistics with percentiles
    - _Requirements: 4.3, 5.4, 5.5, 6.3_
  - [x] 7.3 Write property test for request/response counter consistency


    - **Property 4: Request/Response Counter Consistency**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
  - [x] 7.4 Write property test for tool call aggregation


    - **Property 6: Tool Call Aggregation Correctness**
    - **Validates: Requirements 3.4**
  - [x] 7.5 Write property test for session uniqueness tracking


    - **Property 7: Session Uniqueness Tracking**
    - **Validates: Requirements 4.1**
  - [x] 7.6 Write property test for turn counter accuracy


    - **Property 8: Turn Counter Accuracy**
    - **Validates: Requirements 4.2**
  - [x] 7.7 Write property test for tokens per session calculation


    - **Property 9: Tokens Per Session Calculation**
    - **Validates: Requirements 4.3**
  - [x] 7.8 Write property test for TPS calculation


    - **Property 10: Tokens Per Second (TPS) Calculation**
    - **Validates: Requirements 5.5**
  - [x] 7.9 Write property test for status code recording


    - **Property 13: Status Code Recording**
    - **Validates: Requirements 6.1, 6.2**
  - [x] 7.10 Write property test for status code aggregation


    - **Property 14: Status Code Aggregation**
    - **Validates: Requirements 6.3**
  - [x] 7.11 Implement rolling window statistics



    - Support configurable time windows (1 min, 5 min, 1 hour)
    - Maintain efficient rolling window data structures
    - _Requirements: 6.4_
  - [x] 7.12 Write property test for date range filter correctness


    - **Property 17: Date Range Filter Correctness**
    - **Validates: Requirements 9.6**

-

- [x] 8. Checkpoint - Make sure all tests are passing


  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement REST API endpoints


  - [x] 9.1 Create usage statistics endpoint in src/core/app/routes/usage_routes.py


    - GET /v1/usage/stats - Return aggregated statistics with filter support
    - Support query parameters for all filter dimensions
    - _Requirements: 11.1, 11.2, 11.3_
  - [x] 9.2 Write property test for API filter application


    - **Property 19: API Filter Application**
    - **Validates: Requirements 11.2, 11.3**
  - [x] 9.3 Create recent usage endpoint

    - GET /v1/usage/recent - Return recent usage records
    - Support pagination and session filtering
    - _Requirements: 9.6_
  - [x] 9.4 Create usage export endpoint

    - GET /v1/usage/export - Export usage data as JSON
    - Support date range filtering
    - _Requirements: 10.1, 10.3_
  - [x] 9.5 Implement error handling for invalid parameters

    - Return HTTP 400 with descriptive error messages
    - _Requirements: 11.4_
-

- [x] 10. Checkpoint - Make sure all tests are passing



  - Ensure all tests pass, ask the user if questions arise.
- [x] 11. Integrate with existing proxy infrastructure



- [ ] 11. Integrate with existing proxy infrastructure

  - [x] 11.1 Add usage recording hooks to request middleware


    - Record request timing at entry point
    - Capture user-agent and proxy user context
    - _Requirements: 2.1, 5.2_
  - [x] 11.2 Add usage recording hooks to response middleware

    - Record response timing and status codes
    - Extract tool calls from responses
    - _Requirements: 2.2, 3.1, 5.1, 5.3, 6.1_
  - [x] 11.3 Add usage recording hooks to backend connectors


    - Record backend request/response with timing
    - Extract backend-reported usage
    - _Requirements: 2.3, 2.4, 8.1, 8.2_
  - [x] 11.4 Register services with dependency injection container


    - Add InMemoryUsageStore, UsageRecordingService, StatisticsAggregationService
    - Configure persistence path and flush interval from app config
    - _Requirements: 9.2, 9.3_
  - [x] 11.5 Add configuration options to AppConfig


    - usage_persistence_path: Path for persistence file
    - usage_flush_interval_seconds: Interval for periodic persistence
    - usage_max_records_in_memory: Maximum records to keep in memory
    - _Requirements: 9.3, 9.7_

- [x] 12. Checkpoint - Make sure all tests are passing




  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Final Checkpoint - Make sure all tests are passing



  - Ensure all tests pass, ask the user if questions arise.
