PRIORITIZED FAILURE CATEGORIES
1) Backend service registration issues | ImpactScore=0.85 | Confidence=high
   Root cause (concise): Backend connectors not imported/registered during test initialization
   Affected dependent code (calling → called):
     - tests/conftest.py:get_backend_instance:205
     - src/core/app/application_factory.py:ApplicationBuilder._initialize_services:240
     - src/core/services/backend_service.py:BackendService._get_or_create_backend:455
     - src/connectors/openrouter.py:<module>:199
   Estimated tests fixed if this category is resolved: 35
   Evidence/derivation:
     - Tests currently failing due to this category (IDs/patterns): All tests with "RuntimeError: Backend 'openrouter' not registered in IBackendService"
     - Why they pass after fix: Importing backend_imports will register all backend connectors with the backend registry
   Proposed fix strategy (architecturally aligned):
     - Import backend_imports in application factory to ensure connectors register during app initialization
     - Ensure test environment also imports backend_imports for proper backend registration
   Risks/Mitigations:
     - Risk: Importing backend_imports may have side effects during app startup
     - Mitigation: Use conditional imports or lazy loading if needed

2) Command processing issues | ImpactScore=0.65 | Confidence=high
   Root cause (concise): Command parameter parsing and handling logic has regressions
   Affected dependent code (calling → called):
     - src/core/services/command_service.py:CommandService.process_commands:244
     - src/core/commands/set_command.py:SetCommand.execute:45
     - src/core/commands/unset_command.py:UnsetCommand.execute:38
     - tests/unit/proxy_logic_tests/test_process_text_for_commands.py:TestProcessTextForCommands.test_malformed_set_command:231
   Estimated tests fixed if this category is resolved: 15
   Evidence/derivation:
     - Tests currently failing due to this category (IDs/patterns): Tests with "Unknown parameter" errors, assertion failures on processed text
     - Why they pass after fix: Fixing command parameter parsing and handling logic
   Proposed fix strategy (architecturally aligned):
     - Review and fix command parameter parsing logic
     - Ensure proper validation and error handling for command parameters
   Risks/Mitigations:
     - Risk: Changes to command processing may affect existing functionality
     - Mitigation: Thorough testing of all command-related functionality

3) Session state adapter issues | ImpactScore=0.55 | Confidence=med
   Root cause (concise): Session state adapter not properly converting between dict and object representations
   Affected dependent code (calling → called):
     - src/core/domain/session.py:SessionStateAdapter.__getattr__:65
     - tests/unit/core/test_hello_command.py:test_hello_handler_execution:37
     - tests/unit/proxy_logic_tests/test_process_text_for_commands.py:TestProcessTextForCommands.test_set_interactive_mode:322
   Estimated tests fixed if this category is resolved: 8
   Evidence/derivation:
     - Tests currently failing due to this category (IDs/patterns): "AttributeError: 'dict' object has no attribute 'backend_config'"
     - Why they pass after fix: Proper implementation of session state adapter
   Proposed fix strategy (architecturally aligned):
     - Implement proper session state adapter that handles dict/object conversion
     - Ensure consistent state representation throughout the application
   Risks/Mitigations:
     - Risk: Changes to session state handling may affect session persistence
     - Mitigation: Comprehensive testing of session-related functionality

4) Interface/contract drift | ImpactScore=0.50 | Confidence=med
   Root cause (concise): Missing method implementations in command handlers
   Affected dependent code (calling → called):
     - src/core/services/command_service.py:CommandService.process_commands:244
     - src/core/commands/handlers/project_handler.py:ProjectCommandHandler:25
     - tests/unit/core/test_command_service.py:test_project_command:111
   Estimated tests fixed if this category is resolved: 5
   Evidence/derivation:
     - Tests currently failing due to this category (IDs/patterns): "AttributeError: 'ProjectCommandHandler' object has no attribute 'execute'"
     - Why they pass after fix: Implement missing execute method in command handlers
   Proposed fix strategy (architecturally aligned):
     - Implement missing methods in command handlers to match interface contracts
     - Ensure consistent interface implementation across all command handlers
   Risks/Mitigations:
     - Risk: Adding methods may affect existing functionality
     - Mitigation: Verify interface compliance across all implementations

5) Authentication configuration issues | ImpactScore=0.45 | Confidence=high
   Root cause (concise): Authentication middleware not properly configured for test environment
   Affected dependent code (calling → called):
     - src/core/security/middleware.py:APIKeyMiddleware:45
     - tests/unit/test_models_endpoint.py:test_models_endpoint_lists_all:30
     - tests/unit/test_models_endpoint.py:test_v1_models_endpoint_lists_all:67
   Estimated tests fixed if this category is resolved: 4
   Evidence/derivation:
     - Tests currently failing due to this category (IDs/patterns): Tests with 401 unauthorized errors on /models endpoints
     - Why they pass after fix: Proper authentication configuration for test environment
   Proposed fix strategy (architecturally aligned):
     - Configure authentication middleware to work properly in test environment
     - Ensure test configuration includes proper API keys
   Risks/Mitigations:
     - Risk: Changes to authentication may affect security
     - Mitigation: Thorough testing of authentication functionality

ImpactScore calculation details:
- FailCount: Number of failing tests attributable to the category
- Breadth: Number of modules/packages touched
- Architecture Alignment: How much the fix advances SOLID/DIP migration (0-1)
- Risk/Complexity: Lower risk/complexity → higher score (0-1 inverted)
- Reusability: Likelihood the fix prevents future failures of the same class (0-1)

Formula: ImpactScore = 0.5*normalize(FailCount) + 0.2*normalize(Breadth) + 0.2*ArchitectureAlignment + 0.1*Reusability - 0.2*RiskComplexity