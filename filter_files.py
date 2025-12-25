fixed_files = set([
    'src/core/auth/sso/sso_service.py',
    'src/core/repositories/in_memory_session_repository.py',
    'src/core/services/universal_mcp_client.py',
    'src/core/di/weak_container.py',
    'src/loop_detection/detector.py',
    'src/loop_detection/token_window_loop_detector.py',
    'src/loop_detection/hybrid_detector.py',
    'src/core/ports/streaming_processors.py',
    'src/tool_call_loop/tracker.py',
    'src/loop_detection/analyzer.py',
    'src/core/services/response_processor_service.py',
    'src/core/app/lifecycle.py',
    'src/loop_detection/buffer.py',
    'src/connectors/hybrid_backend/orchestration/injection_policy.py',
    'src/core/domain/health/endpoint_health_state.py',
    'src/services/test_execution_reminder/test_runner_registry.py',
    'src/security.py',
    'src/core/simulation/backend_simulator.py',
    'src/core/services/health/backend_notifier.py',
    'src/core/services/tool_access_policy_service.py',
    'src/core/config/parameter_resolution.py',
    'src/core/services/universal_tool_executor.py',
    'src/core/services/streaming/stream_context_registry.py',
    'src/connectors/openai.py',
    'src/connectors/gemini.py',
    'src/connectors/anthropic.py',
    'src/core/commands/registry.py',
    'src/core/commands/set_parameter_registry.py',
    'src/connectors/gemini_base/model_registry.py',
    'src/codebuff/server.py',
    'src/connectors/base.py',
    'src/performance_tracker.py',
    'src/rate_limit.py',
    'src/core/services/event_bus.py',
    'src/core/interfaces/event_bus_interface.py',
    'src/codebuff/handlers/init_handler.py',
    'src/codebuff/handlers/prompt_handler.py',
    'src/codebuff/handlers/subscription_handler.py',
    'src/core/services/health/icmp_checker.py',
    'src/codebuff/connection_manager.py',
    'src/connectors/gemini_base/thought_signature_manager.py',
    'src/core/services/backend_lifecycle_manager.py',
    'src/core/services/backend_completion_flow/service.py',
    'src/core/memory/capture_middleware.py',
    'src/core/memory/response_capture_processor.py',
    'src/core/repositories/in_memory_config_repository.py',
    'src/core/services/path_validation_service.py',
    'src/core/services/async_usage_write_queue.py',
    'src/core/services/tool_call_reactor_service.py',
    'src/core/services/replacement_metrics.py',
    'src/core/services/unified_tool_security_handler.py',
    'src/services/steering/session_state_store.py',
])

with open('all_files.txt', 'r') as f:
    all_files = [line.strip() for line in f if line.strip()]

remaining = []
for f in all_files:
    # Convert Windows path to forward slash
    path = f.replace('\\', '/')
    # Normalize to src/ format
    if path.startswith('C:/'):
        # Extract path after repo name
        idx = path.find('llm-interactive-proxy/')
        if idx != -1:
            path = 'src/' + path[idx + 22:]
    if path not in fixed_files:
        remaining.append(path)

print('Files to examine:')
for f in sorted(remaining)[:50]:
    print(f)
print(f'Total: {len(remaining)} files')
