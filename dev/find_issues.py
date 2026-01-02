#!/usr/bin/env python3
"""Find exception hygiene issues in Python files."""
import re
from pathlib import Path
import sys

def find_issues(directory):
    """Find exception hygiene issues."""
    issues = []

    for py_file in Path(directory).rglob("*.py"):
        # Skip test files and dev files
        if any(x in str(py_file) for x in ["test", "fixture", "mock", "stub", "dev/", "nul"]):
            continue

        # Skip already fixed files
        fixed_files = [
            "anthropic_oauth.py", "anthropic.py", "cline_auth.py", "openai_codex/credentials.py",
            "mixins/antigravity_auth_mixin.py", "qwen_oauth.py", "gemini_cloud_project.py",
            "opencode_zen.py", "_openai_codex_connector.py", "gemini.py",
            "gemini_base/streaming_executor.py", "gemini_base/token_estimator.py",
            "gemini_base/credential_providers/file_provider.py", "gemini_base/connector.py",
            "hybrid_backend/services/model_spec_parser.py", "domain/translators/responses/response.py",
            "domain/translation_utils/tool_utils.py", "domain/commands/loop_detection_commands/loop_detection_command.py",
            "app/middleware/content_rewriting_middleware.py", "app/middleware_config.py",
            "app/stages/processor.py", "app/stages/test_stages.py",
            "app/controllers/anthropic_controller.py", "app/controllers/responses_controller.py",
            "config/parameter_resolution.py", "config/edit_precision_temperatures.py",
            "config/sources/backend_instances.py", "config/sources/yaml_file.py",
            "cli.py", "cli_support/privilege_checker.py", "commands/service.py",
            "services/cbor_wire_capture_service.py", "services/edit_precision_response_middleware.py",
            "services/angel_prompt_loader.py", "services/assessment_prompt_loader.py",
            "auth/sso/sso_service.py", "core/simulation/client_simulator.py",
            "di/registration_helpers/request_processing/_rp_orchestration_core.py",
            "services/test_execution_reminder/eos_subscriber.py", "loop_detection/streaming.py",
            "gemini_base/credential_coordinator.py", "gemini_base/credential_providers/sqlite_provider.py",
            "services/production_concurrency_guard.py", "openai.py", "openai_codex/executor.py"
        ]

        if any(fixed in str(py_file) for fixed in fixed_files):
            continue

        try:
            content = py_file.read_text()
            lines = content.splitlines()

            # Pattern 1: Find except blocks followed by logger.error/warning without exc_info
            # Look for patterns like: except X as e: ... logger.error("message", e)
            in_except_block = False
            except_var = None
            brace_count = 0

            for i, line in enumerate(lines, 1):
                # Track except blocks
                if re.search(r'except\s+\w+(\s+as\s+\w+)?:', line):
                    in_except_block = True
                    # Extract exception variable if present
                    match = re.search(r'except\s+\w+(?:\s+as\s+(\w+))?:', line)
                    except_var = match.group(1) if match and match.group(1) else None
                    brace_count = line.count('{') - line.count('}')

                elif in_except_block:
                    brace_count += line.count('{') - line.count('}')

                    # Check for logger.error/warning
                    if re.search(r'logger\.(error|warning)\(', line):
                        # Check if exc_info is present
                        if 'exc_info=' not in line:
                            # Check if next line has exc_info
                            if i < len(lines) and 'exc_info=' not in lines[i]:
                                # Found an issue
                                issues.append({
                                    'file': str(py_file),
                                    'line': i,
                                    'type': 'missing_exc_info',
                                    'context': line.strip(),
                                    'exception_var': except_var
                                })
                                # print(f"ISSUE: {py_file}:{i} - logger.{re.search(r'logger\.(error|warning)\(', line).group(1)} without exc_info in except block")
                            in_except_block = False
                            except_var = None

                    # Reset except block if we've moved past it (simple heuristic)
                    if line.strip() and not line.strip().startswith('#') and brace_count == 0:
                        # Only reset if we've seen non-comment, non-whitespace content
                        if not re.search(r'logger\.(error|warning|debug|info)', line) and not re.search(r'raise ', line):
                            in_except_block = False
                            except_var = None

        except Exception as e:
            print(f"Error processing {py_file}: {e}", file=sys.stderr)

    return issues

if __name__ == "__main__":
    issues = find_issues("src")
    for issue in issues:
        print(f"{issue['file']}:{issue['line']} - {issue['type']} - {issue['context'][:80]}")
