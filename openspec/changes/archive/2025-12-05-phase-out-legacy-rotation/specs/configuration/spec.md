# Configuration Spec Delta

## ADDED Requirements

### Requirement: Single API Key Configuration
The system MUST support configuring a single API key for a backend instance via the `api_key` field.
The field type MUST be `str | None`.
The system MUST NOT support a list of API keys for a single instance.

#### Scenario: Single API key
Given a backend config with `api_key="sk-test"`
When the configuration is validated
Then it should be accepted as a valid string

### Requirement: API Key Redaction Discovery
The system MUST discover API keys for redaction from:
1.  The single `api_key` configured for each registered backend.
2.  The `auth.api_keys` list (if used for proxy authentication, distinct from backend keys).
3.  Standard environment variables.

#### Scenario: Discover keys from backend config
Given a backend `openai` with `api_key="sk-test"`
When discovering keys for redaction
Then "sk-test" should be included in the redaction set.
