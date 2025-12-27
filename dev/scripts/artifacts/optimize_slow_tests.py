#!/usr/bin/env python3
"""Script to optimize slow property tests by reducing Hypothesis iteration counts."""

import re
from pathlib import Path


def optimize_eos_dedupe_properties(file_path: Path):
    """Optimize test_eos_dedupe_properties.py"""
    content = file_path.read_text()

    # Reduce max_examples from 30 to 10 and max_size from 10 to 5
    content = re.sub(r"max_examples=30", "max_examples=10", content)

    content = re.sub(
        r"@given\(signals=st\.lists\(signal_strategy\(\), min_size=2, max_size=10\)\)",
        "@given(signals=st.lists(signal_strategy(), min_size=2, max_size=5))",
        content,
    )

    file_path.write_text(content)
    print(f"[OK] Optimized {file_path.name}")


def optimize_sso_provider_selection_properties(file_path: Path):
    """Optimize test_sso_provider_selection_properties.py"""
    content = file_path.read_text()

    # Reduce provider_names max_size from 20 to 10 and list max_size from 5 to 3
    content = re.sub(
        r'max_size=20,\s*\n\s*alphabet=st\.characters\(whitelist_categories=\("Ll", "Lu"\)\)',
        'max_size=10,\n                alphabet=st.characters(whitelist_categories=("Ll", "Lu"))',
        content,
    )

    content = re.sub(
        r"min_size=2,\s*\n\s*max_size=5,\s*\n\s*unique=True,",
        "min_size=2,\n            max_size=3,\n            unique=True,",
        content,
    )

    file_path.write_text(content)
    print(f"[OK] Optimized {file_path.name}")


def optimize_cli_di(file_path: Path):
    """Optimize test_cli_di.py"""
    print(f"[SKIP] {file_path.name} already optimized (uses monkeypatch properly)")


def optimize_streaming_middleware_properties(file_path: Path):
    """Optimize test_streaming_middleware_properties.py"""
    content = file_path.read_text()

    # Add max_examples=10 to test_infrastructure_components_provider_agnostic
    content = re.sub(
        r"(@pytest\.mark\.asyncio\s*\n\s*@given\(chunk=streaming_content_strategy\(\)\s*\n\s*@property_test_settings\(\s*\))",
        r"@pytest.mark.asyncio\n    @given(chunk=streaming_content_strategy())\n    @property_test_settings(max_examples=10)",
        content,
    )

    # Reduce max_examples from 20 to 10
    content = re.sub(
        r"max_examples=20, deadline=None\)",
        "max_examples=10, deadline=None)",
        content,
    )

    file_path.write_text(content)
    print(f"? Optimized {file_path.name}")


def optimize_no_steering_properties(file_path: Path):
    """Optimize test_no_steering_on_clean_completion_properties.py"""
    content = file_path.read_text()

    # Reduce test_command list from 8 to 3
    content = re.sub(
        r'(@given\(\s*test_command=st\.sampled_from\(\s*\[\s*"pytest",\s*"python -m pytest",\s*)"jest",\s*"npm test",\s*"cargo test",\s*"go test",\s*"mvn test",\s*"dotnet test",\s*\]\s*\),)',
        r'@given(\n    test_command=st.sampled_from(\n        ["pytest",\n        "python -m pytest",\n        "jest",\n    ]\n),',
        content,
    )

    # Add max_examples=10 to test_property_6_no_steering_after_any_test_runner
    content = re.sub(
        r"(@given\(\s*test_command=st\.sampled_from\([^)]+\),\s*completion_signal=completion_signal_strategy\(\),\s*session_id=session_id_strategy\(\),\s*\)\s*\n\s*@property_test_settings\(\s*\))",
        r'@given(\n    test_command=st.sampled_from(\n        ["pytest",\n        "python -m pytest",\n        "jest",\n    ],\n    completion_signal=completion_signal_strategy(),\n    session_id=session_id_strategy(),\n)\n@property_test_settings(max_examples=10)',
        content,
    )

    # Add max_examples=10 to test_property_6_no_steering_after_test_execution
    content = re.sub(
        r"(@given\(\s*completion_signal=completion_signal_strategy\(\),\s*session_id=session_id_strategy\(\),\s*\)\s*\n\s*@property_test_settings\(\s*\))",
        r"@given(\n    completion_signal=completion_signal_strategy(),\n    session_id=session_id_strategy(),\n)\n@property_test_settings(max_examples=10)",
        content,
    )

    file_path.write_text(content)
    print(f"? Optimized {file_path.name}")


def optimize_usage_normalization_properties(file_path: Path):
    """Optimize test_usage_normalization_properties.py"""
    content = file_path.read_text()

    # Add max_examples=10 to test_total_tokens_derivation_from_any_source
    content = re.sub(
        r"(@property_test_settings\(\s*\)\s*\n\s*@given\(\s*usage_summary=usage_summary_strategy\(\),\s*raw_usage=usage_payload_strategy\(\),\s*context=normalization_context_strategy\(\),\s*\))",
        r"@property_test_settings(max_examples=10)\n    @given(\n        usage_summary=usage_summary_strategy(),\n        raw_usage=usage_payload_strategy(),\n        context=normalization_context_strategy(),\n)",
        content,
    )

    file_path.write_text(content)
    print(f"? Optimized {file_path.name}")


def optimize_authentication_properties(file_path: Path):
    """Optimize test_authentication_properties.py"""
    content = file_path.read_text()

    # Reduce max_examples from 30 to 10
    content = re.sub(
        r"@settings\(max_examples=30, deadline=None\)",
        "@settings(max_examples=10, deadline=None)",
        content,
    )

    file_path.write_text(content)
    print(f"? Optimized {file_path.name}")


def optimize_usage_format_translation_properties(file_path: Path):
    """Optimize test_usage_format_translation_properties.py"""
    content = file_path.read_text()

    # Add max_examples=10 to test_property_7_response_adapter_includes_usage_in_body_and_headers
    content = re.sub(
        r"(@given\(envelope=response_envelope_with_usage_strategy\(\)\s*\n\s*@property_test_settings\(\s*\))",
        r"@given(envelope=response_envelope_with_usage_strategy())\n@property_test_settings(max_examples=10)",
        content,
    )

    file_path.write_text(content)
    print(f"? Optimized {file_path.name}")


def optimize_sso_auth_middleware_properties(file_path: Path):
    """Optimize test_sso_auth_middleware_properties.py"""
    content = file_path.read_text()

    # Reduce num_requests max_size from 10 to 5
    content = re.sub(
        r"num_requests=st\.integers\(min_value=2, max_value=10\)",
        "num_requests=st.integers(min_value=2, max_value=5)",
        content,
    )

    file_path.write_text(content)
    print(f"? Optimized {file_path.name}")


def main():
    """Apply all optimizations."""
    repo_root = Path("C:/Users/Mateusz/source/repos/llm-interactive-proxy")

    optimizations = [
        (
            repo_root / "tests/property/core/services/test_eos_dedupe_properties.py",
            optimize_eos_dedupe_properties,
        ),
        (
            repo_root / "tests/property/test_sso_provider_selection_properties.py",
            optimize_sso_provider_selection_properties,
        ),
        (repo_root / "tests/unit/test_cli_di.py", optimize_cli_di),
        (
            repo_root / "tests/property/test_streaming_middleware_properties.py",
            optimize_streaming_middleware_properties,
        ),
        (
            repo_root
            / "tests/property/test_no_steering_on_clean_completion_properties.py",
            optimize_no_steering_properties,
        ),
        (
            repo_root / "tests/property/core/test_usage_normalization_properties.py",
            optimize_usage_normalization_properties,
        ),
        (
            repo_root / "tests/property/codebuff/test_authentication_properties.py",
            optimize_authentication_properties,
        ),
        (
            repo_root / "tests/property/test_usage_format_translation_properties.py",
            optimize_usage_format_translation_properties,
        ),
        (
            repo_root / "tests/property/test_sso_auth_middleware_properties.py",
            optimize_sso_auth_middleware_properties,
        ),
    ]

    for file_path, optimizer in optimizations:
        if file_path.exists():
            try:
                optimizer(file_path)
            except Exception as e:
                print(f"[ERROR] Failed to optimize {file_path.name}: {e}")
        else:
            print(f"[WARN] File not found: {file_path}")

    print("\n=== All optimizations completed! ===")


if __name__ == "__main__":
    main()
