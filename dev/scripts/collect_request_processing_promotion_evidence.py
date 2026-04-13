#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.core.services.promotion_guardrail_evaluator import (
    PromotionEvidenceSnapshot,
    PromotionGuardrailEvaluator,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXE = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
DEFAULT_PROMPT = "Say hello in one short sentence."
BENCHMARK_SCRIPT = (
    REPO_ROOT / "dev" / "scripts" / "benchmark_request_processing_migration.py"
)
PROXY_STREAM_SCRIPT = REPO_ROOT / "dev" / "scripts" / "proxy_stream_test.py"
INSPECT_CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "inspect_cbor_capture.py"


@dataclass(frozen=True)
class GroupResult:
    name: str
    passed: bool | None
    status: str
    junit_xml: str | None
    log_file: str | None
    return_code: int | None
    command: str | None
    notes: str | None = None


def compute_percent_delta(candidate: float, baseline: float) -> float:
    denominator = max(float(baseline), 0.001)
    return ((float(candidate) - float(baseline)) / denominator) * 100.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect promotion evidence for request-processing migration."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--baseline-json", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--backend", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--skip-live-capture", action="store_true")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-benchmarks", action="store_true")
    return parser.parse_args()


def _run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _write_log(log_path: Path, result: subprocess.CompletedProcess[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        f"returncode={result.returncode}\n"
        "--- stdout ---\n"
        f"{result.stdout}"
        "\n--- stderr ---\n"
        f"{result.stderr}"
    )
    log_path.write_text(text, encoding="utf-8")


def _parse_junit_passed(xml_path: Path) -> bool:
    if not xml_path.exists():
        return False
    root = ElementTree.fromstring(xml_path.read_text(encoding="utf-8"))
    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = list(root.findall("testsuite"))
    failures = 0
    errors = 0
    for suite in suites:
        failures += int(suite.attrib.get("failures", "0"))
        errors += int(suite.attrib.get("errors", "0"))
    return failures == 0 and errors == 0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _extract_current_ttft_ms(inspection_json: dict[str, Any]) -> float | None:
    entries = inspection_json.get("entries")
    if not isinstance(entries, list):
        return None

    # Prefer explicit metadata when present.
    for entry in entries:
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            continue
        ttfb = metadata.get("ttfb_ms")
        if isinstance(ttfb, int | float):
            return float(ttfb)

    starts: dict[str, float] = {}
    for entry in entries:
        direction = entry.get("direction")
        timestamp = entry.get("timestamp")
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            continue
        request_id = metadata.get("request_id")
        if not isinstance(request_id, str):
            continue
        if direction == "PROXY_TO_BACKEND" and isinstance(timestamp, int | float):
            starts[request_id] = float(timestamp)

    best_ms: float | None = None
    for entry in entries:
        direction = entry.get("direction")
        timestamp = entry.get("timestamp")
        metadata = entry.get("metadata")
        if direction != "BACKEND_TO_PROXY" or not isinstance(timestamp, int | float):
            continue
        if not isinstance(metadata, dict):
            continue
        request_id = metadata.get("request_id")
        if not isinstance(request_id, str):
            continue
        start = starts.get(request_id)
        if start is None:
            continue
        delta_ms = max((float(timestamp) - start) * 1000.0, 0.0)
        if best_ms is None or delta_ms < best_ms:
            best_ms = delta_ms
    return best_ms


def _extract_baseline_ttft_ms(baseline_json: dict[str, Any]) -> float | None:
    candidates = [
        baseline_json.get("current_stream_ttft_ms"),
        baseline_json.get("stream_ttft_ms"),
        baseline_json.get("live_capture", {}).get("current_stream_ttft_ms"),
        baseline_json.get("live_capture", {}).get("stream_ttft_ms"),
        baseline_json.get("evidence", {}).get("current_stream_ttft_ms"),
        baseline_json.get("evidence", {}).get("stream_ttft_ms"),
    ]
    for value in candidates:
        if isinstance(value, int | float):
            return float(value)
    return None


def _run_pytest_group(
    *,
    group_name: str,
    pytest_args: list[str],
    output_dir: Path,
    commands_run: list[str],
    repo_root: Path,
    runner: Any,
) -> GroupResult:
    junit_path = output_dir / "pytest" / f"{group_name}.xml"
    log_path = output_dir / "logs" / f"{group_name}.log"
    command = [
        str(PYTHON_EXE),
        "-m",
        "pytest",
        *pytest_args,
        "--junitxml",
        str(junit_path),
    ]
    commands_run.append(_command_text(command))
    result = runner(command, repo_root)
    _write_log(log_path, result)
    passed = result.returncode == 0 and _parse_junit_passed(junit_path)
    return GroupResult(
        name=group_name,
        passed=passed,
        status="passed" if passed else "failed",
        junit_xml=str(junit_path),
        log_file=str(log_path),
        return_code=result.returncode,
        command=_command_text(command),
    )


def _latest_capture_file(capture_dir: Path) -> Path | None:
    files = [path for path in capture_dir.glob("*.cbor") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime_ns)


def _write_markdown_report(
    *,
    run_id: str,
    output_dir: Path,
    report_path: Path,
    commands_run: list[str],
    group_results: dict[str, GroupResult],
    capture_cbor: Path | None,
    capture_inspection: Path | None,
    summary_path: Path,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Request-Processing Promotion Evidence Report: {run_id}",
        "",
        "## Run Metadata",
        f"- Run ID: `{run_id}`",
        f"- Generated at (UTC): `{dt.datetime.now(dt.timezone.utc).isoformat()}`",
        f"- Evidence output dir: `{output_dir}`",
        "",
        "## Commands Executed",
    ]
    lines.extend(f"- `{command}`" for command in commands_run)
    lines.extend(
        [
            "",
            "## Artifact Paths",
            f"- `pytest/guardrail-gates.xml`: `{output_dir / 'pytest' / 'guardrail-gates.xml'}`",
            f"- `pytest/guardrail-nonstream.xml`: `{output_dir / 'pytest' / 'guardrail-nonstream.xml'}`",
            f"- `pytest/guardrail-streaming.xml`: `{output_dir / 'pytest' / 'guardrail-streaming.xml'}`",
            f"- `pytest/guardrail-memory-cleanup.xml`: `{output_dir / 'pytest' / 'guardrail-memory-cleanup.xml'}`",
            f"- `logs/guardrail-gates.log`: `{output_dir / 'logs' / 'guardrail-gates.log'}`",
            f"- `logs/guardrail-nonstream.log`: `{output_dir / 'logs' / 'guardrail-nonstream.log'}`",
            f"- `logs/guardrail-streaming.log`: `{output_dir / 'logs' / 'guardrail-streaming.log'}`",
            f"- `logs/guardrail-memory-cleanup.log`: `{output_dir / 'logs' / 'guardrail-memory-cleanup.log'}`",
            f"- `summary.json`: `{summary_path}`",
        ]
    )
    if capture_cbor is not None:
        lines.append(f"- `captures/current.cbor`: `{capture_cbor}`")
    if capture_inspection is not None:
        lines.append(f"- `captures/current_inspection.json`: `{capture_inspection}`")
    lines.extend(["", "## Pytest Group Status"])
    for key in (
        "guardrail-gates",
        "guardrail-nonstream",
        "guardrail-streaming",
        "guardrail-memory-cleanup",
    ):
        result = group_results.get(key)
        if result is None:
            lines.append(f"- `{key}`: not-run")
        else:
            lines.append(f"- `{key}`: {result.status}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_evidence(
    args: argparse.Namespace,
    *,
    repo_root: Path = REPO_ROOT,
    runner: Any = _run_command,
) -> int:
    run_id = args.run_id
    output_dir = (
        Path(args.output_dir)
        if args.output_dir is not None
        else repo_root / "var" / "promotion_evidence" / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pytest").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (output_dir / "captures").mkdir(parents=True, exist_ok=True)

    commands_run: list[str] = []
    group_results: dict[str, GroupResult] = {}
    missing_evidence: list[str] = []
    step_failures: list[str] = []

    pytest_groups = {
        "guardrail-gates": [
            "tests/unit/core/services/test_promotion_guardrail_evaluator.py",
            "tests/unit/core/services/test_migration_gate_service.py",
            "tests/unit/core/services/test_backend_request_manager_migration_diagnostics.py",
        ],
        "guardrail-nonstream": [
            "tests/integration/test_canonical_core_path_equivalence.py",
            "tests/integration/test_connector_stream_first_canonical.py",
            "tests/integration/test_backend_request_manager_e2e.py",
            "-k",
            "non_streaming or cleanup",
        ],
        "guardrail-streaming": ["tests/integration/test_streaming_performance.py"],
        "guardrail-memory-cleanup": [
            "tests/regression/test_codex_non_streaming_cleanup_regression.py",
            "tests/regression/test_streaming_registry_cleanup_not_called_regression.py",
            "tests/regression/test_stream_context_registry_ttl_cleanup_regression.py",
            "tests/regression/test_backend_completion_cancellation_task_leak_regression.py",
            "tests/property/test_streaming_memory_properties.py",
        ],
    }

    if args.skip_pytest:
        missing_evidence.extend(
            [
                "characterization_tests_pass (skip-pytest)",
                "equivalence_tests_pass (skip-pytest)",
                "cleanup_checks_pass (skip-pytest)",
            ]
        )
    else:
        for group_name, group_args in pytest_groups.items():
            result = _run_pytest_group(
                group_name=group_name,
                pytest_args=group_args,
                output_dir=output_dir,
                commands_run=commands_run,
                repo_root=repo_root,
                runner=runner,
            )
            group_results[group_name] = result
            if not result.passed:
                step_failures.append(group_name)

    benchmark_json_path = output_dir / "benchmark_request_processing_migration.json"
    non_stream_p95_latency_delta_pct: float | None = None
    memory_delta_pct: float | None = None
    if args.skip_benchmarks:
        missing_evidence.extend(
            [
                "non_stream_p95_latency_delta_pct (skip-benchmarks)",
                "memory_delta_pct (skip-benchmarks)",
            ]
        )
    else:
        benchmark_cmd = [
            str(PYTHON_EXE),
            str(BENCHMARK_SCRIPT),
            "--output",
            str(benchmark_json_path),
        ]
        commands_run.append(_command_text(benchmark_cmd))
        benchmark_result = runner(benchmark_cmd, repo_root)
        _write_log(output_dir / "logs" / "benchmark.log", benchmark_result)
        if benchmark_result.returncode != 0 or not benchmark_json_path.exists():
            step_failures.append("benchmark")
            missing_evidence.extend(
                ["non_stream_p95_latency_delta_pct", "memory_delta_pct"]
            )
        else:
            benchmark_payload = _read_json(benchmark_json_path)
            non_stream_value = (
                benchmark_payload.get("worst_case", {})
                .get("non_stream_p95_latency_delta_pct", {})
                .get("value")
            )
            memory_value = (
                benchmark_payload.get("worst_case", {})
                .get("memory_delta_pct", {})
                .get("value")
            )
            if isinstance(non_stream_value, int | float):
                non_stream_p95_latency_delta_pct = float(non_stream_value)
            else:
                missing_evidence.append("non_stream_p95_latency_delta_pct")
            if isinstance(memory_value, int | float):
                memory_delta_pct = float(memory_value)
            else:
                missing_evidence.append("memory_delta_pct")

    current_stream_ttft_ms: float | None = None
    baseline_stream_ttft_ms: float | None = None
    stream_ttft_delta_pct: float | None = None
    capture_out: Path | None = None
    inspect_out: Path | None = None

    if args.skip_live_capture:
        missing_evidence.append("stream_ttft_delta_pct (skip-live-capture)")
    else:
        if not args.base_url or not args.backend or not args.model:
            step_failures.append("live_capture_arguments")
            missing_evidence.append("stream_ttft_delta_pct")
        else:
            capture_dir = repo_root / "var" / "wire_captures_cbor"
            capture_dir.mkdir(parents=True, exist_ok=True)
            before_latest = _latest_capture_file(capture_dir)
            stream_cmd = [
                str(PYTHON_EXE),
                str(PROXY_STREAM_SCRIPT),
                "--base-url",
                str(args.base_url),
                "--model",
                str(args.model),
                "--prompt",
                str(args.prompt),
            ]
            commands_run.append(_command_text(stream_cmd))
            stream_result = runner(stream_cmd, repo_root)
            _write_log(output_dir / "logs" / "live-capture.log", stream_result)

            if stream_result.returncode != 0:
                step_failures.append("live_capture")
                missing_evidence.append("stream_ttft_delta_pct")
            else:
                after_latest = _latest_capture_file(capture_dir)
                if after_latest is None or after_latest == before_latest:
                    step_failures.append("live_capture_missing_cbor")
                    missing_evidence.append("stream_ttft_delta_pct")
                else:
                    capture_path = after_latest
                    assert capture_path is not None
                    capture_output_path = output_dir / "captures" / "current.cbor"
                    capture_out = capture_output_path
                    shutil.copy2(capture_path, capture_output_path)

                    inspect_output_path = (
                        output_dir / "captures" / "current_inspection.json"
                    )
                    inspect_out = inspect_output_path
                    inspect_cmd = [
                        str(PYTHON_EXE),
                        str(INSPECT_CAPTURE_SCRIPT),
                        str(capture_out),
                        "--analyze",
                        "--analyze-streaming",
                        "--detect-issues",
                        "--status-summary",
                        "--backend",
                        str(args.backend),
                        "--json",
                        str(inspect_output_path),
                    ]
                    commands_run.append(_command_text(inspect_cmd))
                    inspect_result = runner(inspect_cmd, repo_root)
                    _write_log(
                        output_dir / "logs" / "capture-inspection.log", inspect_result
                    )
                    inspect_path = inspect_output_path
                    if inspect_result.returncode != 0 or not inspect_path.exists():
                        step_failures.append("capture_inspection")
                        missing_evidence.append("stream_ttft_delta_pct")
                    else:
                        inspection_payload = _read_json(inspect_path)
                        current_stream_ttft_ms = _extract_current_ttft_ms(
                            inspection_payload
                        )
                        if current_stream_ttft_ms is None:
                            missing_evidence.append("stream_ttft_delta_pct")

                        if args.baseline_json:
                            baseline_path = Path(args.baseline_json)
                            if baseline_path.exists():
                                baseline_payload = _read_json(baseline_path)
                                baseline_stream_ttft_ms = _extract_baseline_ttft_ms(
                                    baseline_payload
                                )
                        if (
                            current_stream_ttft_ms is not None
                            and baseline_stream_ttft_ms is not None
                        ):
                            stream_ttft_delta_pct = compute_percent_delta(
                                current_stream_ttft_ms, baseline_stream_ttft_ms
                            )
                        else:
                            missing_evidence.append("stream_ttft_delta_pct")

    characterization_tests_pass: bool | None
    if args.skip_pytest:
        characterization_tests_pass = None
    else:
        characterization_tests_pass = all(
            bool(result.passed) for result in group_results.values()
        )
    equivalence_tests_pass = group_results.get(
        "guardrail-nonstream",
        GroupResult(
            name="guardrail-nonstream",
            passed=None,
            status="not-run",
            junit_xml=None,
            log_file=None,
            return_code=None,
            command=None,
        ),
    ).passed
    cleanup_checks_pass = group_results.get(
        "guardrail-memory-cleanup",
        GroupResult(
            name="guardrail-memory-cleanup",
            passed=None,
            status="not-run",
            junit_xml=None,
            log_file=None,
            return_code=None,
            command=None,
        ),
    ).passed

    evidence = PromotionEvidenceSnapshot(
        characterization_tests_pass=characterization_tests_pass,
        equivalence_tests_pass=equivalence_tests_pass,
        cleanup_checks_pass=cleanup_checks_pass,
        non_stream_p95_latency_delta_pct=non_stream_p95_latency_delta_pct,
        memory_delta_pct=memory_delta_pct,
        stream_ttft_delta_pct=stream_ttft_delta_pct,
    )
    evaluation = PromotionGuardrailEvaluator().evaluate(
        evidence,
        strict_missing_evidence=True,
    )

    report_path = (
        repo_root
        / "docs"
        / "reports"
        / f"request-processing-promotion-evidence-{run_id}.md"
    )
    summary_path = output_dir / "summary.json"

    summary: dict[str, Any] = {
        "run_id": run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "commands": commands_run,
        "steps": {
            "pytest_groups": {
                name: asdict(result) for name, result in group_results.items()
            },
            "skip_pytest": bool(args.skip_pytest),
            "skip_benchmarks": bool(args.skip_benchmarks),
            "skip_live_capture": bool(args.skip_live_capture),
        },
        "evidence": {
            "characterization_tests_pass": characterization_tests_pass,
            "equivalence_tests_pass": equivalence_tests_pass,
            "cleanup_checks_pass": cleanup_checks_pass,
            "non_stream_p95_latency_delta_pct": non_stream_p95_latency_delta_pct,
            "memory_delta_pct": memory_delta_pct,
            "stream_ttft_delta_pct": stream_ttft_delta_pct,
            "current_stream_ttft_ms": current_stream_ttft_ms,
            "baseline_stream_ttft_ms": baseline_stream_ttft_ms,
        },
        "evaluation": {
            "overall_passed": evaluation.overall_passed,
            "promotion_blocked": evaluation.promotion_blocked,
            "rollback_recommended": evaluation.rollback_recommended,
            "diagnostics": evaluation.diagnostics,
        },
        "missing_evidence": sorted(set(missing_evidence)),
        "step_failures": sorted(set(step_failures)),
        "artifacts": {
            "summary_json": str(summary_path),
            "report_md": str(report_path),
            "benchmark_json": (
                str(benchmark_json_path) if benchmark_json_path.exists() else None
            ),
            "capture_cbor": str(capture_out) if capture_out else None,
            "capture_inspection_json": str(inspect_out) if inspect_out else None,
        },
    }

    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    _write_markdown_report(
        run_id=run_id,
        output_dir=output_dir,
        report_path=report_path,
        commands_run=commands_run,
        group_results=group_results,
        capture_cbor=capture_out,
        capture_inspection=inspect_out,
        summary_path=summary_path,
    )

    if step_failures or not evaluation.overall_passed:
        return 1
    return 0


def main() -> int:
    args = _parse_args()
    return collect_evidence(args)


if __name__ == "__main__":
    sys.exit(main())
