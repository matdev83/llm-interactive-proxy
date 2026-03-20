# Implementation tasks: Nvidia API backend

## Task list

- [x] 1. Nvidia backend: tests, connector implementation, and verification
- [x] 1.1 Add unit tests for connector initialization and headers (TDD red phase first)
  - Assert default hosted API base URL, optional URL override from backend configuration, `NVIDIA_API_KEY` applied only when init kwargs do not already carry an API key, and authorization header shape consistent with other Bearer API-key backends
  - Cover unconfigured behavior: empty discovered model list when no key and no static models list, matching OpenAI-style peers
  - _Requirements: 1.3, 2.1, 2.4, 3.4_
- [x] 1.2 Implement the OpenAI-compatible Nvidia connector and register it for discovery
  - Subclass the shared OpenAI-style connector, set stable backend type identifier, perform import-time registry registration, inherit chat completion and streaming paths and health check against the models listing endpoint
  - Do not introduce alternate registration or request pipelines
  - _Requirements: 1.1, 1.2, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 5.1, 5.2_
- [x] 1.3 Add mandatory usage accounting tests for non-stream and streaming responses
  - Use synthetic JSON fixtures shaped like successful completions with `usage` populated for at least one non-stream case
  - Use SSE-style chunk fixtures (or recorded fragments) for at least one streaming case where usage appears in the stream; if the vendor shape omits stream usage, record that limitation in the backend user guide per design
  - _Requirements: 4.3_
- [x] 1.4 Run connector-focused unit tests then full suite; resolve failures and lint or type issues on touched Python files per project QA rules
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 5.1, 5.2_

- [x] 2. Operator configuration and documentation
- [x] 2.1 (P) Extend the example configuration with a commented Nvidia backend block
  - Document optional fields, default base URL intent, and how `NVIDIA_API_KEY` relates to YAML or CLI key precedence
  - _Requirements: 2.1, 2.3, 6.1_
- [x] 2.2 (P) Add backend user guide page and update the backends overview table
  - Describe how to enable the backend, select `backend:model` values, model naming or endpoint constraints from vendor documentation, and credential sources including the named environment variable
  - _Requirements: 6.1, 6.2_
