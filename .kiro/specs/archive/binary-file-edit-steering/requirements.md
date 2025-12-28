# Requirements Document

## Introduction

This feature adds a new steering policy that detects and warns when an LLM agent attempts to edit binary files. Binary files (executables, compiled libraries, media files, databases, etc.) should generally not be modified through text-based file editing operations, as such modifications typically corrupt the files. The policy integrates with the existing unified steering framework and follows established patterns for configuration (CLI > ENV > YAML precedence).

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining steering/guardrail behaviors for tool calls
- Operators relying on consistent telemetry and configuration controls
- Users of automated agents whose tool calls must be steered safely to prevent file corruption

## Glossary

| Term | Definition |
|------|------------|
| Binary_File | A file containing non-text data that cannot be meaningfully edited as text (executables, media, databases, etc.) |
| Binary_File_Edit_Steering_Policy | The steering policy that detects and warns about binary file edit attempts |
| File_Editing_Tool | A tool that creates, modifies, or deletes files (write_file, str_replace, edit_file, etc.) |
| Steering | Logic that inspects tool-call commands and returns guidance or blocking responses |
| Policy | A discrete rule implementing `ISteeringPolicy` to evaluate a command and optionally steer |

## Requirements

### Requirement 1

**User Story:** As a platform operator, I want the system to detect when an agent attempts to edit binary files, so that I can prevent file corruption from text-based edits to binary content.

#### Acceptance Criteria

1. WHEN a file editing tool call contains a file path with a binary file extension THEN the Binary_File_Edit_Steering_Policy SHALL return a steering result warning the agent not to edit binary files.
2. WHEN a file editing tool call contains a file path with a non-binary extension THEN the Binary_File_Edit_Steering_Policy SHALL return None and allow the operation to proceed.
3. WHEN the Binary_File_Edit_Steering_Policy is disabled via configuration THEN the policy SHALL return None for all tool calls without evaluation.
4. THE Binary_File_Edit_Steering_Policy SHALL recognize file editing tools including: write_to_file, write_file, fsWrite, replace_in_file, str_replace, strReplace, edit_file, patch_file, apply_diff, apply_patch, delete_file, deleteFile, remove_file, create_file, move_file, rename_file, copy_file, insert_content, and search_and_replace.
5. THE Binary_File_Edit_Steering_Policy SHALL extract the target file path from tool arguments using common parameter names (path, file_path, target_file, filename, file, destination).

### Requirement 2

**User Story:** As a platform operator, I want comprehensive coverage of binary file extensions, so that the steering policy catches all common binary file types.

#### Acceptance Criteria

1. THE Binary_File_Edit_Steering_Policy SHALL recognize executable extensions including: .exe, .dll, .so, .dylib, .bin, .elf, .com, .msi, .app, .deb, .rpm, .dmg, .iso, .img.
2. THE Binary_File_Edit_Steering_Policy SHALL recognize compiled/object file extensions including: .o, .obj, .a, .lib, .pyc, .pyo, .class, .jar, .war, .ear, .whl, .egg.
3. THE Binary_File_Edit_Steering_Policy SHALL recognize database extensions including: .db, .sqlite, .sqlite3, .mdb, .accdb, .dbf, .frm, .ibd, .myd, .myi, .ldf, .mdf, .ndf.
4. THE Binary_File_Edit_Steering_Policy SHALL recognize media file extensions including: .mp3, .mp4, .avi, .mkv, .mov, .wmv, .flv, .webm, .wav, .flac, .aac, .ogg, .wma, .m4a, .m4v, .3gp.
5. THE Binary_File_Edit_Steering_Policy SHALL recognize image file extensions including: .jpg, .jpeg, .png, .gif, .bmp, .tiff, .tif, .ico, .webp, .svg, .psd, .ai, .eps, .raw, .cr2, .nef, .heic, .heif.
6. THE Binary_File_Edit_Steering_Policy SHALL recognize document binary formats including: .doc, .docx, .xls, .xlsx, .ppt, .pptx, .pdf, .odt, .ods, .odp.
7. THE Binary_File_Edit_Steering_Policy SHALL recognize archive extensions including: .zip, .tar, .gz, .bz2, .xz, .7z, .rar, .cab, .arj, .lzh, .lzma, .z.
8. THE Binary_File_Edit_Steering_Policy SHALL recognize font extensions including: .ttf, .otf, .woff, .woff2, .eot, .fon.
9. THE Binary_File_Edit_Steering_Policy SHALL recognize other binary formats including: .dat, .pak, .bundle, .asset, .unity3d, .blend, .fbx, .3ds, .max, .dwg, .dxf.
10. THE Binary_File_Edit_Steering_Policy SHALL perform case-insensitive extension matching.

### Requirement 3

**User Story:** As a platform operator, I want to configure the binary file edit steering via CLI flags, environment variables, and config files, so that I can control the feature using my preferred configuration method.

#### Acceptance Criteria

1. WHEN the CLI flag --disable-binary-file-edit-steering is provided THEN the Binary_File_Edit_Steering_Policy SHALL be disabled regardless of other configuration sources.
2. WHEN the environment variable DISABLE_BINARY_FILE_EDIT_STEERING is set to "true" or "1" THEN the Binary_File_Edit_Steering_Policy SHALL be disabled unless overridden by CLI.
3. WHEN the config file entry session.tool_call_reactor.binary_file_edit_steering_enabled is set to false THEN the Binary_File_Edit_Steering_Policy SHALL be disabled unless overridden by ENV or CLI.
4. THE configuration precedence SHALL follow CLI > ENV > YAML ordering.
5. THE Binary_File_Edit_Steering_Policy SHALL be enabled by default when no configuration is specified.

### Requirement 4

**User Story:** As a platform maintainer, I want the binary file edit steering policy to integrate with the unified steering framework, so that it follows established patterns and is maintainable.

#### Acceptance Criteria

1. THE Binary_File_Edit_Steering_Policy SHALL implement the ISteeringPolicy interface.
2. THE Binary_File_Edit_Steering_Policy SHALL be registered in the SteeringStage alongside other policies.
3. THE Binary_File_Edit_Steering_Policy SHALL support prompt override via a Markdown file at config/prompts/steering_binary_file_edit.md.
4. THE Binary_File_Edit_Steering_Policy SHALL emit structured telemetry/log entries consistent with other steering policies.
5. THE Binary_File_Edit_Steering_Policy SHALL have a configurable priority (default: 90) for policy ordering.

### Requirement 5

**User Story:** As a platform maintainer, I want the binary file edit steering policy to be testable, so that I can verify its correctness.

#### Acceptance Criteria

1. THE Binary_File_Edit_Steering_Policy SHALL have unit tests covering binary extension detection.
2. THE Binary_File_Edit_Steering_Policy SHALL have unit tests covering file path extraction from various tool argument formats.
3. THE Binary_File_Edit_Steering_Policy SHALL have unit tests covering the enabled/disabled configuration states.
4. THE Binary_File_Edit_Steering_Policy SHALL have property-based tests verifying extension matching behavior.

## Non-Functional Requirements

### NFR 1: Performance
- Extension matching SHALL use O(1) set lookup operations.
- File path extraction SHALL add negligible overhead to tool call processing.

### NFR 2: Reliability
- The policy SHALL degrade gracefully if file path extraction fails (return None, log warning).
- The policy SHALL handle malformed tool arguments without raising exceptions.

### NFR 3: Observability
- Structured logs SHALL include policy name, matched extension, file path, and outcome.
- Logs SHALL redact sensitive path components consistent with existing steering policies.

### NFR 4: Security
- File path logging SHALL avoid exposing sensitive directory structures where current system redacts.
