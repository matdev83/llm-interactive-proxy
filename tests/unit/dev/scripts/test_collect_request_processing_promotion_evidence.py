from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT / "dev" / "scripts" / "collect_request_processing_promotion_evidence.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "collect_request_processing_promotion_evidence", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_junit(path: Path, *, failures: int = 0, errors: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suite = ElementTree.Element(
        "testsuite", tests="1", failures=str(failures), errors=str(errors)
    )
    tree = ElementTree.ElementTree(suite)
    tree.write(path, encoding="unicode")


def _args(
    *,
    run_id: str,
    output_dir: Path,
    baseline_json: Path | None = None,
    base_url: str | None = "http://127.0.0.1:8000",
    backend: str | None = "openai",
    model: str | None = "gpt-4o-mini",
    prompt: str = "hello",
    skip_live_capture: bool = False,
    skip_pytest: bool = False,
    skip_benchmarks: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        run_id=run_id,
        output_dir=str(output_dir),
        baseline_json=str(baseline_json) if baseline_json is not None else None,
        base_url=base_url,
        backend=backend,
        model=model,
        prompt=prompt,
        skip_live_capture=skip_live_capture,
        skip_pytest=skip_pytest,
        skip_benchmarks=skip_benchmarks,
    )


def test_green_path_collects_evidence_and_writes_bundle(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    output_dir = repo_root / "var" / "promotion_evidence" / "run-green"
    capture_dir = repo_root / "var" / "wire_captures_cbor"
    capture_dir.mkdir(parents=True, exist_ok=True)
    docs_reports = repo_root / "docs" / "reports"
    docs_reports.mkdir(parents=True, exist_ok=True)

    baseline_json = tmp_path / "baseline.json"
    baseline_json.write_text(
        json.dumps({"stream_ttft_ms": 100.0}),
        encoding="utf-8",
    )

    class _Result:
        def __init__(
            self, returncode: int = 0, stdout: str = "", stderr: str = ""
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def runner(command: list[str], cwd: Path):
        del cwd
        if "-m" in command and "pytest" in command:
            junit_path = Path(command[command.index("--junitxml") + 1])
            _write_junit(junit_path, failures=0, errors=0)
            return _Result(0, "pytest ok", "")

        if str(module.BENCHMARK_SCRIPT) in command:
            output_path = Path(command[command.index("--output") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "worst_case": {
                            "non_stream_p95_latency_delta_pct": {"value": 1.0},
                            "memory_delta_pct": {"value": 2.0},
                        }
                    }
                ),
                encoding="utf-8",
            )
            return _Result(0, "benchmark ok", "")

        if str(module.PROXY_STREAM_SCRIPT) in command:
            cbor_file = capture_dir / "captured.cbor"
            cbor_file.write_bytes(b"cbor")
            return _Result(0, "stream ok", "")

        if str(module.INSPECT_CAPTURE_SCRIPT) in command:
            json_path = Path(command[-1])
            json_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "entries": [
                    {
                        "direction": "PROXY_TO_BACKEND",
                        "timestamp": 1.0,
                        "metadata": {"request_id": "req-1"},
                    },
                    {
                        "direction": "BACKEND_TO_PROXY",
                        "timestamp": 1.105,
                        "metadata": {"request_id": "req-1"},
                    },
                ]
            }
            json_path.write_text(json.dumps(payload), encoding="utf-8")
            return _Result(0, "inspect ok", "")

        raise AssertionError(f"Unexpected command: {command}")

    args = _args(run_id="run-green", output_dir=output_dir, baseline_json=baseline_json)
    rc = module.collect_evidence(args, repo_root=repo_root, runner=runner)
    assert rc == 0

    summary_path = output_dir / "summary.json"
    report_path = (
        repo_root
        / "docs"
        / "reports"
        / "request-processing-promotion-evidence-run-green.md"
    )
    assert summary_path.exists()
    assert report_path.exists()
    assert (output_dir / "pytest" / "guardrail-gates.xml").exists()
    assert (output_dir / "pytest" / "guardrail-nonstream.xml").exists()
    assert (output_dir / "pytest" / "guardrail-streaming.xml").exists()
    assert (output_dir / "pytest" / "guardrail-memory-cleanup.xml").exists()
    assert (output_dir / "captures" / "current.cbor").exists()
    assert (output_dir / "captures" / "current_inspection.json").exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["evaluation"]["overall_passed"] is True
    assert summary["evaluation"]["promotion_blocked"] is False
    assert summary["evidence"]["stream_ttft_delta_pct"] == pytest.approx(5.0)

    report = report_path.read_text(encoding="utf-8")
    assert "pytest/guardrail-gates.xml" in report
    assert "captures/current.cbor" in report


def test_missing_baseline_blocks_promotion_and_preserves_summary(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    output_dir = repo_root / "var" / "promotion_evidence" / "run-no-baseline"
    capture_dir = repo_root / "var" / "wire_captures_cbor"
    capture_dir.mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "reports").mkdir(parents=True, exist_ok=True)

    class _Result:
        def __init__(
            self, returncode: int = 0, stdout: str = "", stderr: str = ""
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def runner(command: list[str], cwd: Path):
        del cwd
        if "-m" in command and "pytest" in command:
            _write_junit(Path(command[command.index("--junitxml") + 1]))
            return _Result(0)
        if str(module.BENCHMARK_SCRIPT) in command:
            Path(command[command.index("--output") + 1]).write_text(
                json.dumps(
                    {
                        "worst_case": {
                            "non_stream_p95_latency_delta_pct": {"value": 0.0},
                            "memory_delta_pct": {"value": 0.0},
                        }
                    }
                ),
                encoding="utf-8",
            )
            return _Result(0)
        if str(module.PROXY_STREAM_SCRIPT) in command:
            (capture_dir / "captured.cbor").write_bytes(b"x")
            return _Result(0)
        if str(module.INSPECT_CAPTURE_SCRIPT) in command:
            Path(command[-1]).write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "direction": "PROXY_TO_BACKEND",
                                "timestamp": 1.0,
                                "metadata": {"request_id": "r1"},
                            },
                            {
                                "direction": "BACKEND_TO_PROXY",
                                "timestamp": 1.1,
                                "metadata": {"request_id": "r1"},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return _Result(0)
        raise AssertionError(f"Unexpected command: {command}")

    args = _args(run_id="run-no-baseline", output_dir=output_dir, baseline_json=None)
    rc = module.collect_evidence(args, repo_root=repo_root, runner=runner)
    assert rc == 1

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evidence"]["stream_ttft_delta_pct"] is None
    assert summary["evaluation"]["promotion_blocked"] is True
    assert any("stream_ttft_delta_pct" in item for item in summary["missing_evidence"])


def test_failed_pytest_group_writes_summary_and_exits_nonzero(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    output_dir = repo_root / "var" / "promotion_evidence" / "run-fail"
    (repo_root / "docs" / "reports").mkdir(parents=True, exist_ok=True)

    class _Result:
        def __init__(
            self, returncode: int = 0, stdout: str = "", stderr: str = ""
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def runner(command: list[str], cwd: Path):
        del cwd
        if "-m" in command and "pytest" in command:
            junit_path = Path(command[command.index("--junitxml") + 1])
            if junit_path.name == "guardrail-gates.xml":
                _write_junit(junit_path, failures=1, errors=0)
                return _Result(1, "failed", "")
            _write_junit(junit_path)
            return _Result(0, "ok", "")
        if str(module.BENCHMARK_SCRIPT) in command:
            Path(command[command.index("--output") + 1]).write_text(
                json.dumps(
                    {
                        "worst_case": {
                            "non_stream_p95_latency_delta_pct": {"value": 0.0},
                            "memory_delta_pct": {"value": 0.0},
                        }
                    }
                ),
                encoding="utf-8",
            )
            return _Result(0)
        return _Result(0)

    args = _args(
        run_id="run-fail",
        output_dir=output_dir,
        skip_live_capture=True,
    )
    rc = module.collect_evidence(args, repo_root=repo_root, runner=runner)
    assert rc == 1
    summary_path = output_dir / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert "guardrail-gates" in summary["step_failures"]


def test_skip_live_capture_records_missing_evidence_and_blocks(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    output_dir = repo_root / "var" / "promotion_evidence" / "run-skip-capture"
    (repo_root / "docs" / "reports").mkdir(parents=True, exist_ok=True)

    class _Result:
        def __init__(
            self, returncode: int = 0, stdout: str = "", stderr: str = ""
        ) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def runner(command: list[str], cwd: Path):
        del cwd
        if "-m" in command and "pytest" in command:
            _write_junit(Path(command[command.index("--junitxml") + 1]))
            return _Result(0)
        if str(module.BENCHMARK_SCRIPT) in command:
            Path(command[command.index("--output") + 1]).write_text(
                json.dumps(
                    {
                        "worst_case": {
                            "non_stream_p95_latency_delta_pct": {"value": 0.0},
                            "memory_delta_pct": {"value": 0.0},
                        }
                    }
                ),
                encoding="utf-8",
            )
            return _Result(0)
        raise AssertionError(f"Unexpected command: {command}")

    args = _args(
        run_id="run-skip-capture",
        output_dir=output_dir,
        skip_live_capture=True,
    )
    rc = module.collect_evidence(args, repo_root=repo_root, runner=runner)
    assert rc == 1
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["evaluation"]["promotion_blocked"] is True
    assert any(
        "skip-live-capture" in entry or "stream_ttft_delta_pct" in entry
        for entry in summary["missing_evidence"]
    )
