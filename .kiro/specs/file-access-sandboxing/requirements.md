# Requirements Document

## Introduction

Add file access sandboxing to prevent LLM agents from modifying files outside the project directory. This protects system files while allowing normal work within the project.

## Glossary

- **Proxy**: The LLM Interactive Proxy system
- **File-Changing Tool**: Tool calls that create, modify, or delete files
- **Project Root**: The detected project workspace directory
- **Sandboxing**: Restricts file operations to the project directory

## Requirements

### Requirement 1: Configuration

**User Story:** As a user, I want to enable sandboxing via config, so I can protect my system files.

#### Acceptance Criteria

1. WHEN `--enable-sandboxing` flag is provided, THE Proxy SHALL enable sandboxing
2. WHEN `ENABLE_SANDBOXING=true` env var is set, THE Proxy SHALL enable sandboxing
3. WHEN `sandboxing.enabled: true` in config.yaml, THE Proxy SHALL enable sandboxing
4. THE Proxy SHALL prioritize CLI > env var > config file
5. WHEN sandboxing enabled but no project root detected, THE Proxy SHALL log a warning

### Requirement 2: Project Root Detection

**User Story:** As a user, I want sandboxing to work with detected project roots, so it knows what to protect.

#### Acceptance Criteria

1. WHEN project root is detected for a session, THE Proxy SHALL activate sandboxing for that session
2. WHEN no project root is detected, THE Proxy SHALL allow all file operations
3. THE Proxy SHALL store the normalized absolute path of the project root

### Requirement 3: Tool Detection

**User Story:** As a user, I want the proxy to catch file-changing tools, so nothing bypasses sandboxing.

#### Acceptance Criteria

1. THE Proxy SHALL recognize common file tools: `write_file`, `fsWrite`, `str_replace`, `strReplace`, `edit_file`, `delete_file`, `deleteFile`, `create_file`, `move_file`, `rename_file`, `copy_file`
2. THE Proxy SHALL support regex patterns for tool matching
3. THE Proxy SHALL extract paths from common parameters: `path`, `file_path`, `filepath`, `file`, `target`, `destination`, `source`

### Requirement 4: Path Validation

**User Story:** As a user, I want file operations blocked outside my project, so my system stays safe.

#### Acceptance Criteria

1. WHEN a file tool is detected, THE Proxy SHALL extract and normalize the file path
2. WHEN the path is outside project root, THE Proxy SHALL block the tool call
3. WHEN blocked, THE Proxy SHALL return error: "File operation outside project root detected. Allowed folder: {project_root}"
4. WHEN the path is inside project root, THE Proxy SHALL allow the operation

### Requirement 5: Path Normalization

**User Story:** As a user, I want paths handled correctly on any OS, so sandboxing works everywhere.

#### Acceptance Criteria

1. THE Proxy SHALL resolve relative paths (`../`, `./`) to absolute paths
2. THE Proxy SHALL expand `~/` to home directory
3. THE Proxy SHALL handle Windows (`\`, `C:\`) and Unix (`/`) paths correctly
4. THE Proxy SHALL resolve symlinks before validation
5. WHEN normalization fails, THE Proxy SHALL block the operation

### Requirement 6: Logging

**User Story:** As a user, I want to see what's blocked, so I can debug issues.

#### Acceptance Criteria

1. WHEN blocking a tool call, THE Proxy SHALL log session ID, tool name, path, and project root
2. WHEN path extraction fails, THE Proxy SHALL log a warning
