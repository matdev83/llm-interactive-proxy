<!-- DEPRECATED: This document has been superseded by dev/solid_refactoring_sot.md. It is kept for historical context. See that file for the authoritative plan and status. -->

# Integration Plan: Migrating Existing Functionality to SOLID Architecture

## Phase 1: Bridge Components (Weeks 1-2)

### 1.1 Create Comprehensive Adapter Layer
- Implement `LegacySessionAdapter` to bridge old Session with new ISession
- Create `LegacyConfigAdapter` to connect old config system to new IConfig
- Develop `LegacyCommandAdapter` to adapt old command pattern to new ICommandService

### 1.2 Initialize Both Architectures Simultaneously  
- Modify `main.py` to initialize both old and new DI containers
- Add connection points for both architectures in FastAPI lifespan
- Register adapters in both containers for cross-communication

### 1.3 Implement Feature Flags
- Add feature flags to toggle between old/new implementations
- Create environment variable controls for gradual migration
- Implement logging to track which code path is used

## Phase 2: Core Backend Services Migration (Weeks 3-4)

### 2.1 LLM Backend Integration
- Replace direct backend calls with BackendService
- Inject LegacyBackendAdapter for each provider (OpenAI, Anthropic, etc.)
- Update error handling to use new exception hierarchy

### 2.2 Session Management
- Migrate session state to new SessionState immutable model
- Replace session storage with SessionRepository implementation
- Connect session history tracking to new model

### 2.3 Rate Limiting
- Implement rate limiting through IRateLimiter interface
- Transition rate limit data to new storage system
- Update all request flows to use new rate limiter

## Phase 3: Command Processing (Weeks 5-6)

### 3.1 Command Handling
- Transition command parsing to new CommandService
- Register all existing commands with CommandRegistry
- Update command handlers to use DI for dependencies

### 3.2 Command Responses
- Standardize command response format using new models
- Update response transformation for client compatibility
- Ensure streaming responses work with new architecture

### 3.3 Command-Specific Settings
- Migrate all command settings to domain configuration models
- Update set/unset commands to use new command handlers
- Ensure all command options remain available

## Phase 4: Request/Response Pipeline (Weeks 7-8)

### 4.1 Request Processing
- Refactor endpoint handlers to use RequestProcessor
- Implement middleware for cross-cutting concerns
- Connect authentication to new security services

### 4.2 Response Handling
- Migrate response processing to ResponseProcessor
- Implement response transformation through middleware
- Connect error handling to new exception system

### 4.3 Loop Detection Integration
- Migrate loop detection to ILoopDetector implementation
- Connect response filtering to new middleware chain
- Ensure tool call tracking works with new architecture

## Phase 5: API Endpoint Switchover (Weeks 9-10)

### 5.1 Legacy API Support
- Create backward compatibility endpoints using adapters
- Implement request/response transformation layer
- Document API differences for users

### 5.2 New API Implementation
- Deploy new endpoints alongside legacy endpoints
- Add versioning support for API stability
- Create transition documentation for users

### 5.3 Complete Switchover
- Deprecate legacy endpoints with warnings
- Transition all traffic to new implementation
- Monitor performance and errors closely

## Phase 6: Legacy Code Cleanup (Weeks 11-12)

### 6.1 Remove Feature Flags
- Remove all conditional code paths
- Clean up adapter implementations
- Simplify configuration management

### 6.2 Code Pruning
- Delete obsolete legacy components
- Remove unused imports and variables
- Consolidate duplicate functionality

### 6.3 Documentation Update
- Update API documentation with new architecture
- Create migration guides for plugin developers
- Document internal architecture for contributors

## Testing Strategy

### For Each Phase:
1. Create integration tests that validate both implementations
2. Add unit tests for new components before implementation
3. Implement regression testing for critical paths
4. Perform A/B testing between old and new implementations

### Critical Paths to Test:
- Basic chat completion flow (non-streaming)
- Streaming response handling
- Command processing (all command types)
- Session state management
- Authentication and rate limiting
- Error handling and recovery

## Rollback Strategy

### For Each Integration:
1. Implement feature flags that can be toggled at runtime
2. Create monitoring alerts for unexpected behavior
3. Document rollback procedures for each component
4. Maintain compatibility with previous version

This integration plan ensures a methodical transition while maintaining system stability and backward compatibility throughout the migration process.
