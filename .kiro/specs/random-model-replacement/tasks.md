# Implementation Plan

- [x] 1. Create configuration models and validation

- [x] 1.1 Create ReplacementConfig dataclass in src/core/domain/configuration/

  - Define fields: enabled, probability, backend_model, turn_count
  - Implement validate() method with all validation rules
  - Implement parse_backend_model() method
  - Requirements: 1.1, 1.2, 1.3, 1.7, 2.1, 2.2, 2.3

- [x] 1.2 Write property test for configuration validation

  - **Property 1: Valid probability range**
  - **Property 2: Valid backend:model format**
  - **Property 3: Positive turn count**
  - **Property 5: Configuration validation error messages**
  - **Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.5**

- [x] 1.3 Extend AppConfig to include replacement configuration

  - Add replacement field to AppConfig
  - Add configuration loading from YAML/environment
  - Add configuration validation on startup
  - Requirements: 1.1, 1.2, 1.3

- [x] 1.4 Write property test for configuration loading

  - **Property 1: Valid probability range**
  - **Property 2: Valid backend:model format**
  - **Property 3: Positive turn count**
  - **Validates: Requirements 1.1, 1.2, 1.3**
-

- [x] 2. Create replacement state models

- [x] 2.1 Create ReplacementState dataclass in src/core/domain/

  - Define fields: active, turns_remaining, original_backend, original_model, replacement_backend, replacement_model
  - Implement activate() method
  - Implement decrement_turn() method
  - Implement deactivate() method
  - Implement to_dict() and from_dict() methods for serialization
  - Requirements: 4.1, 4.2, 5.5

- [x] 2.2 Write property test for state transitions

  - **Property 13: Turn counter decrement**
  - **Property 14: Deactivation on counter expiry**
  - **Property 17: Initial session state**
  - **Validates: Requirements 4.1, 4.2, 4.5**

- [x] 2.3 Write property test for state serialization

  - **Property 20: State persistence round-trip**
  - **Validates: Requirements 5.4, 5.5**

- [x] 2.4 Extend SessionState to include replacement state

  - Add replacement_state field to SessionState
  - Add replacement_disabled field to SessionState
  - Implement get_replacement_state() method
  - Implement set_replacement_state() method
  - Requirements: 5.5
-

- [-] 3. Create replacement service interface and implementation

- [x] 3.1 Create IModelReplacementService protocol in src/core/interfaces/

  - Define should_replace() method signature
  - Define get_effective_backend_model() method signature
  - Define complete_turn() method signature
  - Define get_state() method signature
  - Define disable_for_session() method signature
  - Requirements: 3.1, 3.2, 3.3, 4.1, 9.2

- [x] 3.2 Create ModelReplacementService in src/core/services/

  - Implement **init** with config, backend_registry, and optional random_generator
  - Implement configuration validation in **init**
  - Implement backend registry validation in **init**
  - Add session state dictionary and disabled sessions set
  - Add asyncio lock for thread safety
  - Requirements: 2.4, 5.1

- [x] 3.3 Write property test for backend validation

  - **Property 4: Registered backend validation**
  - **Validates: Requirements 2.4**

- [x] 3.4 Implement should_replace() method

  - Check if feature is enabled
  - Check if session is disabled
  - Check for opt-out header
  - Get or create session state
  - Return true if already active
  - Generate random number and compare to probability
  - Log probability check at DEBUG level
  - Requirements: 1.4, 1.5, 3.1, 3.2, 6.4, 9.1, 9.2

- [x] 3.5 Write property test for replacement triggering

  - **Property 6: Probability zero never triggers**
  - **Property 7: Probability one always triggers**
  - **Property 8: Random number range**
  - **Property 9: Probability threshold activation**
  - **Validates: Requirements 1.4, 1.5, 3.1, 3.2**

- [x] 3.6 Implement get_effective_backend_model() method

  - Get session state
  - Return original if not active
  - Return replacement if active
  - Log routing decision at DEBUG level
  - Requirements: 3.3, 3.5, 6.3

- [x] 3.7 Write property test for routing logic

  - **Property 10: Replacement routing**
  - **Property 12: Original routing when inactive**
  - **Property 15: Post-deactivation routing**
  - **Property 16: Continued replacement during window**
  - **Validates: Requirements 3.3, 3.5, 4.3, 4.4**

- [x] 3.8 Implement activate_replacement() method

  - Parse replacement backend:model from config
  - Get or create session state
  - Call state.activate() with parameters
  - Log activation at INFO level
  - Requirements: 3.4, 6.1

- [x] 3.9 Write property test for activation
  - **Property 11: Turn counter initialization**
  - **Property 21: Activation logging**
  - **Validates: Requirements 3.4, 6.1**

- [x] 3.10 Implement complete_turn() method

  - Get session state
  - Call state.decrement_turn() if active
  - Log deactivation at INFO level if deactivated
  - Requirements: 4.1, 4.2, 6.2

- [x] 3.11 Write property test for turn completion
  - **Property 13: Turn counter decrement**
  - **Property 14: Deactivation on counter expiry**
  - **Property 22: Deactivation logging**
  - **Validates: Requirements 4.1, 4.2, 6.2**

- [x] 3.12 Implement get_state() method

  - Get or create session state
  - Return state
  - Requirements: 5.1

- [x] 3.13 Implement disable_for_session() method

  - Add session to disabled set
  - Deactivate any active replacement
  - Log disable action at INFO level
  - Requirements: 9.2, 9.5

- [x] 3.14 Write property test for session disable
  - **Property 32: Session-level opt-out**
  - **Property 35: Immediate deactivation on disable**
  - **Validates: Requirements 9.2, 9.5**

- [x] 3.15 Implement cleanup_session() method

  - Remove session from state dictionary
  - Remove session from disabled set
  - Requirements: 5.3

- [x] 3.16 Write property test for session isolation
  - **Property 18: Independent session states**
  - **Property 19: Session cleanup**
  - **Validates: Requirements 5.1, 5.2, 5.3**
-

- [x] 4. Integrate replacement service with request processor

- [x] 4.1 Update RequestProcessor constructor

  - Add optional replacement_service parameter
  - Store replacement_service as instance variable
  - Requirements: 7.1

- [x] 4.2 Update process_request() method to apply replacement

  - Store original backend and model
  - Check if replacement service exists
  - Call should_replace() to check if replacement should trigger
  - If should replace and not active, call activate_replacement()
  - Call get_effective_backend_model() to get effective backend:model
  - Update context.backend and request_data.model
  - Requirements: 3.2, 3.3, 3.4, 7.1

- [x] 4.3 Write property test for request processor integration

  - **Property 26: Command processing order**
  - **Validates: Requirements 7.1**

- [x] 4.4 Update process_request() to complete turn after response

  - Add try/finally block around backend request
  - Call complete_turn() in finally block
  - Ensure turn completion happens even on error
  - Requirements: 4.1, 10.3

- [x] 4.5 Write property test for turn completion timing

  - **Property 38: Streaming turn completion**
  - **Validates: Requirements 10.3**

- [x] 5. Add replacement service to dependency injection

- [x] 5.1 Register ModelReplacementService in service collection

  - Add registration in src/core/di/services.py
  - Configure with AppConfig.replacement
  - Inject BackendRegistry dependency
  - Requirements: 1.1, 2.4

- [x] 5.2 Update RequestProcessor factory to inject replacement service

  - Resolve IModelReplacementService from service provider
  - Pass to RequestProcessor constructor
  - Handle case where service is not registered (disabled)
  - Requirements: 7.1
-

- [x] 6. Add configuration schema and examples

- [x] 6.1 Create JSON schema for replacement configuration

  - Add schema to config/schemas/
  - Define all fields with types and constraints
  - Add descriptions for each field
  - Requirements: 1.1, 1.2, 1.3

- [x] 6.2 Add example configuration to config/config.example.yaml

  - Add commented replacement section
  - Show example with probability=0.3
  - Show example backend_model format
  - Show example turn_count
  - Requirements: 1.1, 1.2, 1.3

- [x] 6.3 Update configuration documentation

  - Document replacement configuration in docs/
  - Explain each parameter
  - Provide usage examples
  - Requirements: 1.1, 1.2, 1.3

- [x] 7. Add opt-out header support

- [x] 7.1 Update should_replace() to check for opt-out header

  - Check request_context.headers for "x-disable-replacement"
  - Return False if header is "true"
  - Log opt-out at DEBUG level
  - Requirements: 9.1, 9.3

- [x] 7.2 Write property test for header opt-out

  - **Property 31: Header-based opt-out**
  - **Property 33: Opt-out logging**
  - **Property 34: Opt-out routing guarantee**
  - **Validates: Requirements 9.1, 9.3, 9.4**
- [x] 8. Add logging throughout replacement service

- [x] 8. Add logging throughout replacement service

- [x] 8.1 Add INFO logging for service initialization

  - Log enabled status, probability, backend_model, turn_count
  - Requirements: 6.5

- [x] 8.2 Write property test for initialization logging

  - **Property 25: Configuration loading logging**
  - **Validates: Requirements 6.5**

- [x] 8.3 Add DEBUG logging for probability checks

  - Log session_id, random value, threshold, result
  - Requirements: 6.4

- [x] 8.4 Write property test for probability logging

  - **Property 24: Probability check logging**
  - **Validates: Requirements 6.4**

- [x] 8.5 Add DEBUG logging for routing decisions

  - Log session_id and effective backend:model
  - Requirements: 6.3

- [x] 8.6 Write property test for routing logging

  - **Property 23: Routing logging**
  - **Validates: Requirements 6.3**

- [x] 9. Add compatibility with existing features

- [x] 9.1 Verify tool filtering works with replacement

  - Test that tool filtering is applied to replacement models
  - Ensure filtered tools are passed to replacement backend
  - Requirements: 7.2

- [x] 9.2 Write property test for tool filtering compatibility

  - **Property 27: Tool filtering preservation**
  - **Validates: Requirements 7.2**

- [x] 9.3 Verify wire capture works with replacement

  - Test that wire capture records replacement requests
  - Ensure both original and replacement models are captured
  - Requirements: 7.3

- [x] 9.4 Write property test for wire capture compatibility

  - **Property 28: Wire capture completeness**
  - **Validates: Requirements 7.3**

- [x] 9.5 Verify usage accounting works with replacement

  - Test that usage is attributed to effective backend:model
  - Ensure replacement model usage is tracked correctly
  - Requirements: 7.4

- [x] 9.6 Write property test for usage attribution

  - **Property 29: Usage attribution accuracy**
  - **Validates: Requirements 7.4**

- [x] 9.7 Verify agent configuration is preserved

  - Test that agent config is maintained with replacement
  - Ensure agent settings are not lost during replacement
  - Requirements: 7.5

- [x] 9.8 Write property test for agent preservation

  - **Property 30: Agent configuration preservation**
  - **Validates: Requirements 7.5**

- [x] 10. Add streaming support

- [x] 10.1 Verify streaming works with replacement models

  - Test that stream=True requests work with replacement
  - Ensure streaming responses are returned correctly
  - Requirements: 10.1

- [x] 10.2 Write property test for streaming with replacement

  - **Property 36: Streaming with replacement**
  - **Validates: Requirements 10.1**

- [x] 10.3 Verify streaming format consistency

  - Test that streaming format matches original backend
  - Ensure no format changes when using replacement
  - Requirements: 10.2

- [x] 10.4 Write property test for streaming format

  - **Property 37: Streaming format consistency**
  - **Validates: Requirements 10.2**

- [x] 10.5 Verify streaming error handling

  - Test that streaming errors are handled consistently
  - Ensure error handling matches original backend
  - Requirements: 10.4

- [x] 10.6 Write property test for streaming errors

  - **Property 39: Streaming error handling**
  - **Validates: Requirements 10.4**

- [x] 10.7 Verify streaming context association

  - Test that streaming context uses effective backend:model
  - Ensure correct backend:model is associated with session
  - Requirements: 10.5

- [x] 10.8 Write property test for streaming context

  - **Property 40: Streaming context association**
  - **Validates: Requirements 10.5**
- [x] 11. Add integration tests

- [x] 11. Add integration tests

- [x] 11.1 Write integration test for full request flow with replacement

  - Test complete request processing with replacement active
  - Verify request reaches correct backend
  - Verify response is returned correctly
  - Requirements: 3.2, 3.3, 4.1

- [x] 11.2 Write integration test for multi-turn replacement

  - Test replacement persists for configured turn count
  - Verify counter decrements correctly
  - Verify deactivation after turns expire
  - Requirements: 4.1, 4.2, 4.3

- [x] 11.3 Write integration test for concurrent sessions

  - Test multiple sessions with independent replacement state
  - Verify no cross-session interference
  - Verify session cleanup
  - Requirements: 5.1, 5.2, 5.3

- [x] 11.4 Write integration test for opt-out mechanisms

  - Test header-based opt-out
  - Test session-level opt-out
  - Verify immediate deactivation on disable
  - Requirements: 9.1, 9.2, 9.5
- [x] 12. Checkpoint - Ensure all tests pass

- [x] 12. Checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Add error handling and fallback

- [x] 13.1 Add error handling for replacement backend unavailable

  - Catch backend connection errors
  - Fall back to original backend
  - Log warning with error details
  - Requirements: 3.3

- [x] 13.2 Add error handling for state corruption

  - Detect invalid state
  - Reset to inactive state
  - Log error with state details
  - Requirements: 5.1

- [x] 13.3 Add error handling for configuration errors

  - Catch validation errors during initialization
  - Log detailed error message
  - Prevent service startup with invalid config
  - Requirements: 2.1, 2.2, 2.3, 2.4, 2.5

- [x] 13.4 Write unit tests for error handling

  - Test backend unavailable fallback
  - Test state corruption recovery
  - Test configuration error handling
  - Requirements: 2.5

- [x] 14. Add performance optimizations

- [x] 14.1 Optimize state lookup with caching

  - Use dictionary for O(1) lookup
  - Minimize lock contention
  - Requirements: 5.1

- [x] 14.2 Optimize probability evaluation

  - Use efficient random number generation
  - Cache configuration values
  - Requirements: 3.1

- [x] 14.3 Write performance tests

  - Measure latency impact of replacement logic
  - Verify overhead is less than 1ms per request
  - Test with high concurrency
  - Requirements: 3.1, 5.1

- [x] 15. Add monitoring and metrics

- [x] 15.1 Add metric for replacement activation rate

  - Track number of activations per time period
  - Track activation rate by session
  - Requirements: 3.2

- [x] 15.2 Add metric for replacement turn count distribution

  - Track distribution of turn counts
  - Track average turns per activation
  - Requirements: 4.1

- [x] 15.3 Add metric for opt-out rate

  - Track number of opt-outs per time period
  - Track opt-out rate by session
  - Requirements: 9.1, 9.2

- [x] 16. Update documentation

- [x] 16.1 Add feature documentation to docs/user_guide/
  - Explain what the feature does
  - Provide configuration examples
  - Explain use cases
  - Requirements: 1.1, 1.2, 1.3

- [x] 16.2 Add API documentation for replacement service
  - Document IModelReplacementService interface
  - Document ModelReplacementService class
  - Document configuration model
  - Requirements: 1.1, 3.1

- [x] 16.3 Update CHANGELOG.md
  - Add entry for new feature
  - List all new configuration options
  - Note any breaking changes (none expected)
  - Requirements: 1.1

- [x] 17. Final checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.
