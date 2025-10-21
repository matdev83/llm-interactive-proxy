# PRD: LLM-Based Conversation Assessment System

## Overview

This feature replicates the sophisticated LLM-based validation system found in Google's `gemini-cli` coding agent, which uses a smaller LLM to periodically assess conversation quality and detect unproductive patterns. The system acts as an intelligent "meta-reviewer" that can identify when the main conversation has become stuck in loops, repetitive behaviors, or cognitive dead-ends.

## Background & Inspiration

The `gemini-cli` project implements an event-driven validation system in `packages/core/src/services/loopDetectionService.ts` that:
- Monitors conversation turns and triggers assessment after configurable thresholds
- Uses the same model with specialized prompts to analyze conversation history
- Provides steering messages when unproductive patterns are detected
- Dynamically adjusts assessment frequency based on confidence levels

## Problem Statement

Current LLM interactions can suffer from:
1. **Repetitive Tool Calls**: Agents getting stuck calling the same tools repeatedly
2. **Cognitive Loops**: Models expressing confusion or asking the same questions
3. **Lack of Progress**: Conversations that continue without meaningful advancement
4. **Resource Waste**: Continued processing of unproductive conversations
5. **User Frustration**: Long conversations that don't reach resolution

## Goals

### Primary Goals
- **G1**: Implement event-driven conversation assessment that triggers after configurable turn thresholds
- **G2**: Detect unproductive conversation patterns using LLM-based analysis
- **G3**: Generate steering messages to help conversations get back on track
- **G4**: Provide configurable assessment intervals and models
- **G5**: Integrate seamlessly with existing middleware pipeline

### Secondary Goals
- **G6**: Support multiple backend/model combinations for assessment
- **G7**: Provide detailed logging and telemetry for assessment decisions
- **G8**: Allow fine-tuning of assessment sensitivity and frequency
- **G9**: Support session-level disable/enable controls

## Success Metrics

- **Reduction in repetitive tool call sequences** by 70%
- **Improved conversation resolution rates** by 40%
- **User satisfaction scores** increase by 25%
- **Assessment accuracy** > 85% (validated through manual review)
- **Performance impact** < 5% latency increase

## User Stories

### Core Functionality
- **US1**: As a developer, I want to enable LLM assessment via CLI flag so I can test the feature easily
- **US2**: As an operator, I want to configure assessment via environment variables so I can control it in production
- **US3**: As a system admin, I want to specify which model performs assessments so I can optimize costs
- **US4**: As a user, I want the system to detect when I'm stuck so conversations become more productive

### Configuration & Control
- **US5**: As a developer, I want to configure the turn threshold so I can tune when assessment starts
- **US6**: As an operator, I want to adjust assessment frequency so I can balance accuracy vs performance
- **US7**: As a system admin, I want to disable assessment for specific sessions so I can handle edge cases
- **US8**: As a developer, I want detailed logs of assessment decisions so I can debug and improve the system

## Functional Requirements

### Core Assessment Engine
- **FR1**: Monitor conversation turn count and trigger assessment after configurable threshold (default: 30 turns)
- **FR2**: Analyze recent conversation history (configurable window, default: 20 turns) for unproductive patterns
- **FR3**: Generate confidence scores (0.0-1.0) for assessment decisions
- **FR4**: Trigger steering interventions when confidence exceeds threshold (default: 0.9)
- **FR5**: Dynamically adjust assessment frequency based on confidence levels

### Pattern Detection
- **FR6**: Detect repetitive tool call sequences (same tool with same/similar parameters)
- **FR7**: Identify cognitive loops (repeated questions, confusion expressions, illogical responses)
- **FR8**: Recognize lack of progress (no meaningful advancement toward task completion)
- **FR9**: Distinguish between legitimate incremental progress and true loops

### Configuration System
- **FR10**: Support CLI parameters for enable/disable and basic configuration
- **FR11**: Support environment variables for production deployment
- **FR12**: Support YAML configuration for complex scenarios
- **FR13**: Allow specification of assessment model (backend + model name)
- **FR14**: Provide configuration validation and error handling

### Integration & Middleware
- **FR15**: Integrate with existing middleware pipeline without breaking changes
- **FR16**: Support streaming and non-streaming responses
- **FR17**: Maintain session state for turn counting and assessment history
- **FR18**: Provide hooks for custom assessment logic

## Technical Requirements

### Performance
- **TR1**: Assessment latency must not exceed 2 seconds for 95th percentile
- **TR2**: Memory usage increase must not exceed 50MB per active session
- **TR3**: Assessment requests must not impact main conversation flow
- **TR4**: Support concurrent assessment requests across multiple sessions

### Reliability
- **TR5**: Assessment failures must not break main conversation flow
- **TR6**: Graceful degradation when assessment model is unavailable
- **TR7**: Retry logic for transient assessment failures
- **TR8**: Circuit breaker pattern for persistent assessment failures

### Security
- **TR9**: Assessment requests must respect same security constraints as main requests
- **TR10**: No sensitive data leakage in assessment logs
- **TR11**: Assessment model access must use proper authentication
- **TR12**: Rate limiting for assessment requests

### Observability
- **TR13**: Comprehensive logging of assessment decisions and reasoning
- **TR14**: Metrics for assessment frequency, accuracy, and performance
- **TR15**: Telemetry integration with existing monitoring systems
- **TR16**: Debug mode for detailed assessment analysis

## Configuration Specification

### CLI Parameters
```bash
--enable-llm-assessment / --disable-llm-assessment
--llm-assessment-turn-threshold INTEGER (default: 30)
--llm-assessment-confidence-threshold FLOAT (default: 0.9)
--llm-assessment-backend STRING (default: same as main backend)
--llm-assessment-model STRING (default: same as main model)
--llm-assessment-history-window INTEGER (default: 20)
--llm-assessment-min-interval INTEGER (default: 5)
--llm-assessment-max-interval INTEGER (default: 15)
```

### Environment Variables
```bash
LLM_ASSESSMENT_ENABLED=true|false
LLM_ASSESSMENT_TURN_THRESHOLD=30
LLM_ASSESSMENT_CONFIDENCE_THRESHOLD=0.9
LLM_ASSESSMENT_BACKEND=openai
LLM_ASSESSMENT_MODEL=gpt-4o-mini
LLM_ASSESSMENT_HISTORY_WINDOW=20
LLM_ASSESSMENT_MIN_INTERVAL=5
LLM_ASSESSMENT_MAX_INTERVAL=15
```

### YAML Configuration
```yaml
llm_assessment:
  enabled: true
  turn_threshold: 30
  confidence_threshold: 0.9
  backend: "openai"
  model: "gpt-4o-mini"
  history_window: 20
  intervals:
    min: 5
    max: 15
    default: 3
  patterns:
    tool_call_repetition_threshold: 3
    cognitive_loop_indicators:
      - "I'm not sure"
      - "Let me try again"
      - "I'm confused"
  disable_for_sessions: []
```

## Assessment Prompt Design

### System Prompt (based on gemini-cli)
```
You are a sophisticated AI diagnostic agent specializing in identifying when a conversational AI is stuck in an unproductive state. Your task is to analyze the provided conversation history and determine if the assistant has ceased to make meaningful progress.

An unproductive state is characterized by one or more of the following patterns over the last 5 or more assistant turns:

1. **Repetitive Actions**: The assistant repeats the same tool calls or conversational responses multiple times. This includes simple loops (e.g., tool_A, tool_A, tool_A) and alternating patterns (e.g., tool_A, tool_B, tool_A, tool_B).

2. **Cognitive Loop**: The assistant seems unable to determine the next logical step. It might express confusion, repeatedly ask the same questions, or generate responses that don't logically follow from the previous turns.

3. **Lack of Progress**: The conversation continues but without meaningful advancement toward the stated goal or task completion.

Crucially, differentiate between a true unproductive state and legitimate, incremental progress. For example, a series of similar tool calls that make small, distinct changes (like adding docstrings to functions one by one) is considered forward progress and is NOT a loop.

Respond in JSON format with:
- reasoning: Your analysis of the conversation state
- confidence: A number between 0.0 and 1.0 representing your confidence that the conversation is unproductive
```

## Non-Functional Requirements

### Scalability
- Support 1000+ concurrent sessions with assessment enabled
- Horizontal scaling through stateless assessment service design
- Efficient memory management for conversation history storage

### Maintainability
- Modular design allowing easy extension of assessment patterns
- Clear separation between assessment logic and middleware integration
- Comprehensive test coverage (>90%) for assessment algorithms

### Usability
- Zero-configuration operation with sensible defaults
- Clear error messages and troubleshooting guidance
- Documentation with examples and best practices

## Constraints & Assumptions

### Constraints
- Must maintain backward compatibility with existing middleware
- Assessment model calls count against user quotas/rate limits
- Cannot modify core chat message structures
- Must work with all supported backends (OpenAI, Anthropic, Gemini, etc.)

### Assumptions
- Users have access to models suitable for assessment tasks
- Assessment latency is acceptable for the use case
- Conversation history is available and properly formatted
- Session state can be maintained across requests

## Risk Assessment

### High Risk
- **Performance Impact**: Assessment calls could significantly slow down conversations
  - *Mitigation*: Async assessment, circuit breakers, performance monitoring
- **False Positives**: Incorrectly identifying productive conversations as loops
  - *Mitigation*: Careful prompt tuning, confidence thresholds, user feedback loops

### Medium Risk
- **Model Availability**: Assessment model might be unavailable or rate-limited
  - *Mitigation*: Graceful degradation, fallback models, retry logic
- **Configuration Complexity**: Too many configuration options could confuse users
  - *Mitigation*: Sensible defaults, clear documentation, validation

### Low Risk
- **Integration Issues**: Conflicts with existing middleware
  - *Mitigation*: Thorough testing, gradual rollout, feature flags

## Success Criteria

### Phase 1 (MVP)
- [ ] Basic assessment engine with turn threshold triggering
- [ ] Simple repetitive pattern detection
- [ ] CLI and environment variable configuration
- [ ] Integration with one backend (OpenAI)

### Phase 2 (Enhanced)
- [ ] Advanced pattern detection (cognitive loops, progress analysis)
- [ ] Dynamic interval adjustment based on confidence
- [ ] YAML configuration support
- [ ] Multi-backend support

### Phase 3 (Production Ready)
- [ ] Comprehensive observability and metrics
- [ ] Performance optimization and caching
- [ ] Advanced configuration options
- [ ] Production deployment and monitoring

## Future Enhancements

- **Custom Assessment Models**: Support for specialized assessment models
- **Pattern Learning**: ML-based improvement of pattern detection
- **User Feedback Integration**: Learning from user corrections
- **Assessment Caching**: Avoiding redundant assessments
- **Multi-Modal Assessment**: Support for image/file-based conversations
- **Assessment APIs**: External access to assessment capabilities

## References

- **gemini-cli source**: `dev/thrdparty/gemini-cli/packages/core/src/services/loopDetectionService.ts`
- **System prompt reference**: Lines 61-75 in loopDetectionService.ts
- **Configuration constants**: Lines 33-55 in loopDetectionService.ts
- **Assessment logic**: `checkForLoopWithLLM()` method starting around line 300