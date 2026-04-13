from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT / "dev" / "scripts" / "benchmark_request_processing_migration.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "benchmark_request_processing_migration", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_calculate_p95_uses_nearest_rank() -> None:
    module = _load_module()

    values = list(range(1, 101))

    assert module.calculate_p95(values) == 95.0


def test_select_worst_case_scenario_returns_highest_delta() -> None:
    module = _load_module()

    scenario_values = {
        "canonical_non_stream_blocking": -1.0,
        "connector_stream_first_non_stream": 7.25,
    }

    name, value = module.select_worst_case_scenario(scenario_values)

    assert name == "connector_stream_first_non_stream"
    assert value == 7.25


def test_compute_percent_delta_uses_expected_formula() -> None:
    module = _load_module()

    delta = module.compute_percent_delta(candidate=125.0, baseline=100.0)

    assert delta == 25.0


def test_compute_percent_delta_uses_baseline_floor_for_zero_or_near_zero() -> None:
    module = _load_module()

    zero_baseline = module.compute_percent_delta(candidate=1.0, baseline=0.0)
    near_zero_baseline = module.compute_percent_delta(candidate=1.0, baseline=0.0002)

    assert zero_baseline == 100000.0
    assert near_zero_baseline == 99980.0
