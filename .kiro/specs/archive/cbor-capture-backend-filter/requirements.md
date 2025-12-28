# Requirements Document

## Introduction

The `inspect_cbor_capture.py` script is a debugging tool for analyzing CBOR wire capture files. Currently, it can filter entries by traffic direction (client_to_proxy, proxy_to_client, proxy_to_backend, backend_to_proxy), but it lacks the ability to filter by backend name. This feature is essential for debugging scenarios where multiple backends are used in a single capture session, allowing developers to isolate and analyze traffic for a specific backend without noise from other backends.

## Glossary

- **CBOR**: Concise Binary Object Representation - a binary data format used for wire captures
- **Wire Capture**: Binary-encoded request/response data captured during proxy operations
- **Backend**: An LLM service provider (e.g., OpenAI, Anthropic, Gemini) that the proxy communicates with
- **Backend Filter**: A parameter that restricts analysis to entries related to a specific backend
- **Capture Entry**: A single recorded event in a wire capture file containing timestamp, direction, and data
- **Capture Metadata**: Optional information attached to entries including backend name, model, session ID, etc.

## Requirements

### Requirement 1

**User Story:** As a developer debugging multi-backend scenarios, I want to filter CBOR capture entries by backend name, so that I can focus on traffic related to a specific backend without noise from other backends.

#### Acceptance Criteria

1. WHEN a user specifies a `--backend` parameter with a valid backend name THEN the script SHALL display only entries where the capture metadata contains that backend name
2. WHEN a user specifies a `--backend` parameter with an invalid or non-existent backend name THEN the script SHALL display a warning message and show zero entries matching that backend
3. WHEN the `--backend` parameter is not specified THEN the script SHALL display all entries without filtering by backend (current behavior)
4. WHEN a user specifies `--backend` with `--analyze` flag THEN the script SHALL analyze only request/response pairs where both request and response entries are associated with the specified backend
5. WHEN a user specifies `--backend` with `--entries` flag THEN the script SHALL display only the specified number of entries that match the backend filter

### Requirement 2

**User Story:** As a developer, I want to discover which backends are present in a capture file, so that I can know what backend names to use for filtering.

#### Acceptance Criteria

1. WHEN a user specifies `--list-backends` flag THEN the script SHALL display a list of all unique backend names found in the capture file with entry counts for each
2. WHEN a capture file contains no backend metadata THEN the script SHALL display a message indicating no backend information is available
3. WHEN a capture file contains entries with and without backend metadata THEN the script SHALL list only backends that have at least one entry with backend metadata

### Requirement 3

**User Story:** As a developer, I want clear documentation about the backend filter feature, so that I can use it effectively in my debugging workflow.

#### Acceptance Criteria

1. WHEN the script is invoked with `--help` THEN the help text SHALL include documentation for the `--backend` parameter with examples
2. WHEN the script is invoked with `--help` THEN the help text SHALL include documentation for the `--list-backends` parameter
3. WHEN documentation files reference the inspect_cbor_capture.py script THEN they SHALL include examples showing how to use the backend filter parameter
4. WHEN documentation files reference the inspect_cbor_capture.py script THEN they SHALL include examples showing how to use the `--list-backends` parameter to discover available backends

