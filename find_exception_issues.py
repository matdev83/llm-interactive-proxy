"""Find exception hygiene issues in codebase."""
import re
from pathlib import Path

# Files to exclude (already fixed)
EXCLUDED_FILES = [
    "anthropic_oauth.py",
    "anthropic.py",
    "cline_auth.py",
    "openai_codex/credentials.py",
    "mixins/antigravity_auth_mixin.py",
    "qwen_oauth.py",
    "gemini_cloud_project.py",
    "opencode_zen.py",
    "_openai_codex_connector.py",
    "gemini.py",
    "gemini_base/streaming_executor.py",
    "gemini_base/token_estimator.py",
    "gemini_base/credential_providers/file_provider.py",
    "gemini_base/connector.py",
    "hybrid_backend/services/model_spec_parser.py",
    "response.py",
    "tool_utils.py",
    "loop_detection_commands/loop_detection_command.py",
    "content_rewriting_middleware.py",
    "middleware_config.py",
    "processor.py",
    "test_stages.py",
    "anthropic_controller.py",
    "responses_controller.py",
    "parameter_resolution.py",
    "edit_precision_temperatures.py",
    "backend_instances.py",
    "yaml_file.py",
    "cli.py",
    "privilege_checker.py",
    "service.py",
    "cbor_wire_capture_service.py",
    "edit_precision_response_middleware.py",
    "angel_prompt_loader.py",
    "assessment_prompt_loader.py",
    "sso_service.py",
    "client_simulator.py",
    "_rp_orchestration_core.py",
    "eos_subscriber.py",
    "streaming.py",
    "credential_coordinator.py",
    "sqlite_provider.py",
    "production_concurrency_guard.py",
    "openai.py",
    "executor.py",
    "session_key_resolver.py",
    "model_utils.py",
    "sse_bytes_parser.py",
    "codebuff/server.py",
    "codebuff/connection_manager.py",
    "antigravity_oauth.py",
    "request_deduplication_service.py",
    "model_discovery.py",
    "response_processors.py",
    "summary_generator.py",
]

def should_exclude(filepath: str) -> bool:
    """Check if file should be excluded."""
    for excluded in EXCLUDED_FILES:
        if excluded in filepath:
            return True
    # Skip test files, __pycache__, etc.
    if "test_" in filepath or "__pycache__" in filepath:
        return True
    if filepath.endswith(".pyc"):
        return True
    return False

def check_file(filepath: Path):
    """Check a single file for exception hygiene issues."""
    issues = []

    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        # Look for exception handlers
        match = re.match(r'^(\s*)except\s+([^:]+):', line)
        if match:
            indent = len(match.group(1))
            exception_types = match.group(2).strip()

            # Check if this is a broad exception handler
            if exception_types == "Exception":
                # Look ahead for logging statements within the next 20 lines
                for j in range(i, min(i + 20, len(lines) + 1)):
                    next_line = lines[j - 1]  # 0-indexed
                    next_indent = len(next_line) - len(next_line.lstrip())

                    # Stop if we exit the except block
                    if next_indent <= indent and next_line.strip():
                        break

                    # Look for logger.error or logger.warning
                    log_match = re.search(r'logger\.(error|warning)\(', next_line)
                    if log_match:
                        # Check if exc_info=True is present
                        # Can be on same line or in next few lines
                        has_exc_info = False
                        # Check same line
                        if 'exc_info=True' in next_line or 'exc_info=include_stack_trace' in next_line:
                            has_exc_info = True
                        # Check next few lines for exc_info parameter
                        for k in range(j, min(j + 3, len(lines) + 1)):
                            if 'exc_info=' in lines[k - 1]:
                                has_exc_info = True
                                break
                        # Check if it's logger.exception() (which includes exc_info automatically)
                        if 'logger.exception(' in next_line:
                            has_exc_info = True

                        if not has_exc_info:
                            issues.append({
                                'file': str(filepath),
                                'line': i,
                                'type': 'missing_exc_info',
                                'exception': exception_types,
                                'log_line': j,
                                'context': f"Exception handler at line {i} has logger.{log_match.group(1)}() without exc_info"
                            })
                        break  # Only report first log in this except block

            # Check if it's a silent handler (just 'pass')
            for j in range(i, min(i + 10, len(lines) + 1)):
                next_line = lines[j - 1]
                next_indent = len(next_line) - len(next_line.lstrip())

                # Stop if we exit the except block
                if next_indent <= indent and next_line.strip():
                    break

                if next_line.strip() == 'pass':
                    # Check if there's any logging before the pass
                    has_logging = False
                    for k in range(i, j):
                        if 'logger.' in lines[k - 1]:
                            has_logging = True
                            break

                    if not has_logging:
                        issues.append({
                            'file': str(filepath),
                            'line': i,
                            'type': 'silent_handler',
                            'exception': exception_types,
                            'context': f"Exception handler at line {i} silently suppresses {exception_types}"
                        })
                    break

    return issues

def check_incorrect_exc_info(filepath: Path):
    """Check for incorrect exc_info usage (exc_info=e instead of exc_info=True)."""
    issues = []

    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        # Look for exc_info=e pattern (incorrect)
        if re.search(r'exc_info\s*=\s*\w+', line):
            # Make sure it's not exc_info=True
            if 'exc_info=True' not in line and 'exc_info=False' not in line:
                # Check if it's logging
                if 'logger.' in line:
                    issues.append({
                        'file': str(filepath),
                        'line': i,
                        'type': 'incorrect_exc_info',
                        'context': f"Incorrect exc_info usage at line {i}: should be exc_info=True, not exc_info=variable"
                    })

    return issues

def main():
    """Main entry point."""
    src_dir = Path("src")
    all_issues = []

    for py_file in src_dir.rglob("*.py"):
        if should_exclude(str(py_file)):
            continue

        issues = check_file(py_file)
        issues.extend(check_incorrect_exc_info(py_file))
        if issues:
            all_issues.extend(issues)

    # Print results
    if all_issues:
        print(f"Found {len(all_issues)} exception hygiene issues:")
        print("=" * 80)
        for issue in all_issues:
            print(f"\nFile: {issue['file']}")
            print(f"Line: {issue['line']}")
            print(f"Type: {issue['type']}")
            if 'exception' in issue:
                print(f"Exception: {issue['exception']}")
            print(f"Context: {issue['context']}")
            print("-" * 80)
    else:
        print("No exception hygiene issues found!")

if __name__ == "__main__":
    main()
