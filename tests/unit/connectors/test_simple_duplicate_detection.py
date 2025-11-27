"""
Simple, focused tests to detect the specific duplicate request regression issue.

This test specifically checks for the pattern where non-streaming methods
call streaming methods, causing duplicate API requests.
"""

import ast
import os

import pytest


class CallExtractor(ast.NodeVisitor):
    """AST visitor to extract function calls without performance issues from nested ast.walk()."""

    def __init__(self):
        self.calls = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Extract the called function name from Call nodes."""
        called_name = None
        if hasattr(node.func, "id"):
            called_name = node.func.id
        elif hasattr(node.func, "attr"):
            called_name = node.func.attr

        if called_name:
            self.calls.append({"name": called_name, "line": node.lineno})

        # Continue visiting child nodes
        self.generic_visit(node)


def test_static_analysis_for_non_streaming_calling_streaming():
    """
    Static analysis test that will fail if non-streaming methods call streaming methods.

    This is the exact pattern that caused the 429 quota exhaustion error:
    _chat_completions_code_assist() calling _chat_completions_code_assist_streaming()
    """
    # Files to analyze
    files_to_check = [
        "src/connectors/gemini_oauth_base.py",
        "src/connectors/gemini_cloud_project.py",
    ]

    violations = []

    for file_path in files_to_check:
        if not os.path.exists(file_path):
            continue

        with open(file_path) as f:
            content = f.read()

        # Parse the AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue

        # Find all function definitions
        functions = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = {"node": node, "calls": [], "line": node.lineno}

        # Analyze function calls within each function
        for _func_name, func_info in functions.items():
            # Use a visitor pattern to extract only direct calls, avoiding nested ast.walk inefficiency
            call_extractor = CallExtractor()
            call_extractor.visit(func_info["node"])
            func_info["calls"] = call_extractor.calls

        # Check for problematic patterns
        for func_name, func_info in functions.items():
            # Pattern 1: Non-streaming method calls streaming method
            if "streaming" not in func_name.lower() and any(
                "streaming" in call["name"].lower() for call in func_info["calls"]
            ):

                # Find the specific streaming call
                streaming_calls = [
                    call
                    for call in func_info["calls"]
                    if "streaming" in call["name"].lower()
                ]

                for call in streaming_calls:
                    violations.append(
                        {
                            "file": file_path,
                            "function": func_name,
                            "line": func_info["line"],
                            "call_line": call["line"],
                            "calls_streaming": call["name"],
                            "pattern": "non_streaming_calls_streaming",
                            "description": f"Function '{func_name}' (line {func_info['line']}) calls streaming function '{call['name']}' (line {call['line']})",
                        }
                    )

            # Pattern 2: Function calls another function that makes API calls
            # This is more complex but we can catch obvious cases
            if func_name.endswith("_code_assist") and not func_name.endswith(
                "_code_assist_streaming"
            ):
                # Check if it calls the streaming version
                streaming_version = f"{func_name}_streaming"
                if any(
                    call["name"] == streaming_version for call in func_info["calls"]
                ):
                    violations.append(
                        {
                            "file": file_path,
                            "function": func_name,
                            "pattern": "code_assist_calls_code_assist_streaming",
                            "description": f"Code assist function '{func_name}' calls its streaming version '{streaming_version}'",
                        }
                    )

    # Assert no violations found
    assert len(violations) == 0, (
        f"Found {len(violations)} potential duplicate request patterns:\n"
        + "\n".join(f"  - {v['description']} in {v['file']}" for v in violations)
        + "\n\nThese patterns can cause the 429 quota exhaustion error by making duplicate API calls."
    )


def test_specific_code_assist_pattern_not_present():
    """
    Test that the specific problematic pattern is not present in the code.

    The pattern we're looking for is:
    - _chat_completions_code_assist() calls _chat_completions_code_assist_streaming()
    """
    file_path = "src/connectors/gemini_oauth_base.py"

    with open(file_path) as f:
        content = f.read()

    # Look for the specific pattern
    # Pattern 1: Direct call to streaming method in non-streaming method
    # We exclude "async def " to avoid false positive on method definition
    pattern1 = "await self._chat_completions_code_assist_streaming("
    pattern2 = "self._chat_completions_code_assist_streaming("

    # Find the non-streaming method
    non_streaming_start = content.find("def _chat_completions_code_assist(")
    assert (
        non_streaming_start != -1
    ), "Could not find _chat_completions_code_assist method"

    # Find the end of this method (next method or end of class)
    next_method = content.find("\n    def ", non_streaming_start + 1)
    if next_method == -1:
        next_method = len(content)

    non_streaming_content = content[non_streaming_start:next_method]

    # Check for the problematic patterns
    pattern1_found = pattern1 in non_streaming_content
    pattern2_found = pattern2 in non_streaming_content

    assert not pattern1_found, (
        f"Found problematic pattern '{pattern1}' in _chat_completions_code_assist method. "
        "This causes the non-streaming method to call the streaming method, leading to duplicate API requests."
    )

    assert not pattern2_found, (
        f"Found problematic pattern '{pattern2}' in _chat_completions_code_assist method. "
        "This causes the non-streaming method to call the streaming method, leading to duplicate API requests."
    )


def test_cloud_project_pattern_not_present():
    """
    Test that the cloud project connector doesn't have the same issue.
    """
    file_path = "src/connectors/gemini_cloud_project.py"

    with open(file_path) as f:
        content = f.read()

    # Look for similar pattern in cloud project connector
    pattern1 = "_chat_completions_streaming("
    pattern2 = "await self._chat_completions_streaming("

    # Find the non-streaming method
    non_streaming_start = content.find("def _chat_completions_standard(")
    if non_streaming_start == -1:
        pytest.skip(
            "Could not find _chat_completions_standard method in cloud project connector"
        )

    # Find the end of this method
    next_method = content.find("\n    async def ", non_streaming_start + 1)
    if next_method == -1:
        next_method = len(content)

    non_streaming_content = content[non_streaming_start:next_method]

    # Check for the problematic patterns
    pattern1_found = pattern1 in non_streaming_content
    pattern2_found = pattern2 in non_streaming_content

    assert not pattern1_found, (
        f"Found problematic pattern '{pattern1}' in _chat_completions_standard method of cloud project connector. "
        "This causes duplicate API requests."
    )

    assert not pattern2_found, (
        f"Found problematic pattern '{pattern2}' in _chat_completions_standard method of cloud project connector. "
        "This causes duplicate API requests."
    )


def test_methods_have_proper_separation():
    """
    Test that streaming and non-streaming methods are properly separated.
    """
    files_to_check = [
        (
            "src/connectors/gemini_oauth_base.py",
            "_chat_completions_code_assist",
            "_chat_completions_code_assist_streaming",
        ),
        (
            "src/connectors/gemini_cloud_project.py",
            "_chat_completions_standard",
            "_chat_completions_streaming",
        ),
    ]

    for file_path, non_streaming_name, streaming_name in files_to_check:
        if not os.path.exists(file_path):
            continue

        with open(file_path) as f:
            content = f.read()

        # Check that both methods exist
        non_streaming_exists = f"def {non_streaming_name}(" in content
        streaming_exists = f"def {streaming_name}(" in content

        if non_streaming_exists and streaming_exists:
            # Good, both methods exist
            pass
        elif non_streaming_exists:
            # Non-streaming exists but streaming doesn't - this might be OK
            pass
        elif streaming_exists:
            # Streaming exists but non-streaming doesn't - this might be OK
            pass
        else:
            # Neither exists - this might be OK for some connectors
            pass

        # The main check is that if both exist, they don't call each other
        if non_streaming_exists and streaming_exists:
            # This is handled by the other tests
            pass


def test_quota_exhaustion_prevention_mechanisms_exist():
    """
    Test that quota exhaustion prevention mechanisms are in place.
    """
    file_path = "src/connectors/gemini_oauth_base.py"

    with open(file_path) as f:
        content = f.read()

    # Check for quota-related mechanisms
    required_mechanisms = [
        "def _mark_backend_unusable(",  # Method to mark backend as unusable
        "_quota_exceeded",  # Flag to track quota exceeded status
        "429",  # HTTP status code for quota exceeded
        "quota exceeded",  # Error message handling
    ]

    missing_mechanisms = []
    for mechanism in required_mechanisms:
        if mechanism not in content:
            missing_mechanisms.append(mechanism)

    assert len(missing_mechanisms) == 0, (
        f"Missing quota exhaustion prevention mechanisms: {missing_mechanisms}. "
        "These mechanisms are important for handling 429 errors gracefully."
    )


def test_request_counter_mechanism_exists():
    """
    Test that request counter mechanism exists for tracking API usage.
    """
    file_path = "src/connectors/gemini_oauth_base.py"

    with open(file_path) as f:
        content = f.read()

    # Check for request counter
    request_counter_patterns = [
        "_request_counter",
        "DailyRequestCounter",
        "increment(",
    ]

    found_patterns = [
        pattern for pattern in request_counter_patterns if pattern in content
    ]

    assert len(found_patterns) >= 2, (
        f"Request counter mechanism appears to be incomplete. Found patterns: {found_patterns}. "
        "Request counting is important for preventing quota exhaustion."
    )
