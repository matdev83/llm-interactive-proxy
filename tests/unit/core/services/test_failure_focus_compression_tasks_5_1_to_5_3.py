"""Tasks 5.1-5.3: failure focus, diagnostics grouping, pytest compatibility."""

from __future__ import annotations

from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategies import (
    DiagnosticsGroupingStrategy,
    FailureFocusGenericStrategy,
    PytestFailureFocusStrategy,
)
from src.core.services.pytest_output_filter import filter_pytest_output
from src.core.services.response_manager_service import AgentResponseFormatter


def _ctx(
    content: str,
    *,
    signature: str | None = "pytest",
    prefix: str | None = None,
    category: str = "command_execution",
) -> ToolOutputContext:
    return ToolOutputContext.for_text(
        tool_name="shell",
        tool_category=category,
        content=content,
        command_signature=signature,
        command_prefix=prefix,
    )


def test_filter_pytest_output_matches_legacy_formatter() -> None:
    fmt = AgentResponseFormatter()
    sample = (
        "============================= test session starts =============================\n"
        "collected 2 items\n"
        "PASSED tests/test_x.py::test_a 0.01s setup\n"
        "FAILED tests/test_x.py::test_b\n"
        "E   assert 1 == 2\n"
        "=========================== short test summary info ===========================\n"
        "FAILED tests/test_x.py::test_b\n"
        "========================= 1 failed, 1 passed in 0.12s ========================="
    )
    assert fmt._filter_pytest_output(sample) == filter_pytest_output(sample)


def test_pytest_failure_focus_preserves_sole_failure_context_and_summary() -> None:
    strategy = PytestFailureFocusStrategy()
    body = (
        "noise line\n"
        "PASSED a 1s call\n"
        "FAIL something\n"
        "detail line\n"
        "==== 1 failed in 1s ===="
    )
    out = strategy.compress(
        body,
        context=_ctx(body),
        level=CompressionLevel.BALANCED,
    )
    assert "PASSED" not in out
    assert "FAIL something" in out
    assert out.endswith("==== 1 failed in 1s ====")


def test_pytest_failure_focus_noop_without_pytest_identity_or_shape() -> None:
    strategy = PytestFailureFocusStrategy()
    text = "PASSED is a word in prose\nnot pytest\n"
    out = strategy.compress(
        text,
        context=_ctx(text, signature="git", prefix="git status"),
        level=CompressionLevel.BALANCED,
    )
    assert out == text


def test_diagnostics_grouping_by_file_and_rule_sorted() -> None:
    strategy = DiagnosticsGroupingStrategy()
    raw = (
        "b.py:2:1: W9 second\n"
        "a.py:1:2: E1 first occurrence\n"
        "a.py:3:2: E1 duplicate message\n"
        "a.py:1:2: E1 first occurrence\n"
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, signature="ruff"),
        level=CompressionLevel.BALANCED,
    )
    assert out.startswith("=== grouped diagnostics ===")
    assert out.index("a.py") < out.index("b.py")
    assert "[E1] L1:C2 first occurrence (x2)" in out
    assert "[E1] L3:C2 duplicate message" in out
    assert "[W9] L2:C1 second" in out
    assert "(x2)" in out


def test_diagnostics_grouping_uses_deterministic_smallest_anchor() -> None:
    strategy = DiagnosticsGroupingStrategy()
    raw = (
        "a.py:40:9: E1 same message\n"
        "a.py:10:3: E1 same message\n"
        "a.py:20:1: E1 same message\n"
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, signature="ruff"),
        level=CompressionLevel.BALANCED,
    )
    assert "[E1] L10:C3 same message (x3, +2 locations)" in out


def test_diagnostics_grouping_preserves_mypy_line_anchor() -> None:
    strategy = DiagnosticsGroupingStrategy()
    raw = (
        "pkg/mod.py:15: error: Incompatible return value type\n"
        "pkg/mod.py:16: note: See https://mypy.readthedocs.io/\n"
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, signature="mypy"),
        level=CompressionLevel.BALANCED,
    )
    assert "[ERROR] L15 Incompatible return value type" in out
    assert "[NOTE] L16 See https://mypy.readthedocs.io/" in out


def test_diagnostics_grouping_preserves_tsc_line_and_column_anchor() -> None:
    strategy = DiagnosticsGroupingStrategy()
    raw = (
        "src/app.ts(9,12): error TS2322: Type 'number' is not assignable to type 'string'\n"
        "src/app.ts(9,12): error TS2322: Type 'number' is not assignable to type 'string'\n"
    )
    out = strategy.compress(
        raw,
        context=_ctx(raw, signature="tsc"),
        level=CompressionLevel.BALANCED,
    )
    assert (
        "[TS2322] L9:C12 Type 'number' is not assignable to type 'string' (x2)" in out
    )


def test_diagnostics_grouping_fail_open_for_unstructured_text() -> None:
    strategy = DiagnosticsGroupingStrategy()
    raw = "just some logs\nno diagnostics here\n"
    out = strategy.compress(
        raw,
        context=_ctx(raw, signature="ruff"),
        level=CompressionLevel.BALANCED,
    )
    assert out == raw


def test_failure_focus_generic_strips_cargo_progress_keeps_errors() -> None:
    strategy = FailureFocusGenericStrategy()
    lines = [
        "Compiling foo v1",
        "Checking bar v2",
        "error[E0425]: cannot find value `x`",
    ]
    lines.extend([f"context {i}" for i in range(15)])
    body = "\n".join(lines)
    out = strategy.compress(
        body,
        context=_ctx(body, signature="cargo", prefix="cargo test"),
        level=CompressionLevel.BALANCED,
    )
    assert "Compiling" not in out
    assert "Checking" not in out
    assert "error[E0425]" in out


def test_failure_focus_generic_zero_failures_summary_minimal() -> None:
    strategy = FailureFocusGenericStrategy()
    filler = "\n".join(f"line {i} ok" for i in range(20))
    body = f"{filler}\ntest result: ok. 14 passed; 0 ignored; 0 measured"
    out = strategy.compress(
        body,
        context=_ctx(body, signature="something"),
        level=CompressionLevel.BALANCED,
    )
    assert "[failure-focus]" in out
    assert "no failures" in out.lower()
    assert "test result: ok" in out


def test_failure_focus_generic_preserves_when_stripping_would_drop_only_failure() -> (
    None
):
    strategy = FailureFocusGenericStrategy()
    body = "\n".join(
        [
            "Compiling foo v1",
            "Checking bar v2",
            "thread 'main' panicked at 'oops'",
        ]
        + [f"stack {i}" for i in range(20)]
    )
    out = strategy.compress(
        body,
        context=_ctx(body, signature="cargo"),
        level=CompressionLevel.BALANCED,
    )
    assert "panicked" in out
