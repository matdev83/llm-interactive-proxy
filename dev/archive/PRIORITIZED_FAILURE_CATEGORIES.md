PRIORITIZED FAILURE CATEGORIES

1) Backend service registration issues | ImpactScore=0.85 | Confidence=high
   Root cause (concise): Backend connectors not imported/registered during test initialization
   Affected dependent code (calling → called):
     - tests/conftest.py:get_backend_instance:205
     - src/core/app/application_factory.py:ApplicationBuilder._initialize_services:240
     - src/core/services/backend_service.py:BackendService._get_or_create_backend:455
     - src/connectors/openrouter.py:<module>:199
   Estimated tests fixed if this category is resolved: 35

2) Command processing issues | ImpactScore=0.65 | Confidence=high
   Root cause (concise): Command parameter parsing and handling logic has regressions
   Affected dependent code (calling → called):
     - src/core/services/command_service.py:CommandService.process_commands:244
     - src/core/commands/set_command.py:SetCommand.execute:45
     - src/core/commands/unset_command.py:UnsetCommand.execute:38
     - tests/unit/proxy_logic_tests/test_process_text_for_commands.py:TestProcessTextForCommands.test_malformed_set_command:231
   Estimated tests fixed if this category is resolved: 15

3) Session state adapter issues | ImpactScore=0.55 | Confidence=med
   Root cause (concise): Session state adapter not properly converting between dict and object representations
   Affected dependent code (calling → called):
     - src/core/domain/session.py:SessionStateAdapter.__getattr__:65
     - tests/unit/core/test_hello_command.py:test_hello_handler_execution:37
     - tests/unit/proxy_logic_tests/test_process_text_for_commands.py:TestProcessTextForCommands.test_set_interactive_mode:322
   Estimated tests fixed if this category is resolved: 8

4) Interface/contract drift | ImpactScore=0.50 | Confidence=med
   Root cause (concise): Missing method implementations in command handlers
   Affected dependent code (calling → called):
     - src/core/services/command_service.py:CommandService.process_commands:244
     - src/core/commands/handlers/project_handler.py:ProjectCommandHandler:25
     - tests/unit/core/test_command_service.py:test_project_command:111
   Estimated tests fixed if this category is resolved: 5

5) Authentication configuration issues | ImpactScore=0.45 | Confidence=high
   Root cause (concise): Authentication middleware not properly configured for test environment
   Affected dependent code (calling → called):
     - src/core/security/middleware.py:APIKeyMiddleware:45
     - tests/unit/test_models_endpoint.py:test_models_endpoint_lists_all:30
     - tests/unit/test_models_endpoint.py:test_v1_models_endpoint_lists_all:67
   Estimated tests fixed if this category is resolved: 4


