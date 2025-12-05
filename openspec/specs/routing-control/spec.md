# routing-control Specification

## Purpose
TBD - created by archiving change 2025-12-05-configurable-routing-policies. Update Purpose after archive.
## Requirements
### Requirement: Configurable Routing Restrictions
The system MUST allow administrators to selectively disable specific routing methods via configuration.

#### Scenario: Default Behavior
Given no routing restrictions are configured
When a user routes via explicit instance ID (e.g., "openai.1:gpt-4")
Then the request should proceed
When a user routes via backend name (e.g., "openai:gpt-4")
Then the request should proceed
When a user routes via model name only (e.g., "gpt-4")
Then the request should proceed

#### Scenario: Disable Backend IDs
Given `disable_routing_with_backend_ids` is enabled
When a user routes via explicit instance ID (e.g., "openai.1:gpt-4")
Then the system should reject the request with a RoutingError
When a user routes via backend name (e.g., "openai:gpt-4")
Then the request should proceed

#### Scenario: Disable Backend Names
Given `disable_routing_with_backend_names` is enabled
When a user routes via backend name (e.g., "openai:gpt-4")
Then the system should reject the request with a RoutingError
When a user routes via explicit instance ID (e.g., "openai.1:gpt-4")
Then the system should reject the request (implied restriction)

#### Scenario: Disable Model Names
Given `disable_routing_with_only_model_names` is enabled
When a user routes via model name only (e.g., "gpt-4")
Then the system should reject the request with a RoutingError
When a user routes via backend name (e.g., "openai:gpt-4")
Then the request should proceed

### Requirement: Configuration Precedence
The system MUST respect configuration from CLI flags, environment variables, and config files in that order of precedence.

#### Scenario: CLI overrides Env
Given `DISABLE_ROUTING_WITH_BACKEND_IDS=false` in environment
And `--disable-routing-with-backend-ids` passed to CLI
When a user routes via backend ID
Then the request should be rejected

- CLI Flag: `--disable-routing-with-backend-ids`
- Env Var: `DISABLE_ROUTING_WITH_BACKEND_IDS`
- Config: `routing.disable_backend_ids`

(And similarly for other flags)

### Requirement: Invalid Configuration Prevention
The system MUST prevent invalid configurations where all routing methods are disabled or conflicting restrictions are applied (e.g., disabling model-only routing AND backend names simultaneously, leaving no valid way to route).

#### Scenario: All disabled
Given config disables backend IDs, backend names, and model names
When the application starts
Then it should fail validation or warn the user

