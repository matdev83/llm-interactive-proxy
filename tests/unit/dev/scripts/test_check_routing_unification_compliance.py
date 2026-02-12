from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "dev" / "scripts" / "check_routing_unification_compliance.py"
INVENTORY_PATH = REPO_ROOT / "dev" / "routing" / "unified_routing_inventory.yaml"


def _load_compliance_module():
    spec = importlib.util.spec_from_file_location(
        "routing_unification_compliance", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_inventory_declares_required_outbound_call_surfaces() -> None:
    module = _load_compliance_module()
    inventory = module.load_inventory(INVENTORY_PATH)
    call_surface_ids = {entry["id"] for entry in inventory["call_surfaces"]}

    required_ids = {
        "primary_request_execution",
        "random_model_replacement",
        "quality_verifier_verification",
        "quality_verifier_correction",
        "auxiliary_sidecar_inference",
    }
    assert required_ids.issubset(call_surface_ids)


def test_run_checks_detects_inventory_drift(tmp_path: Path) -> None:
    module = _load_compliance_module()
    service_file = tmp_path / "src" / "core" / "services" / "sample.py"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(
        "async def run(backend_service, request):\n"
        "    return await backend_service.chat_completions(request)\n",
        encoding="utf-8",
    )

    inventory_file = tmp_path / "dev" / "routing" / "unified_routing_inventory.yaml"
    inventory_file.parent.mkdir(parents=True, exist_ok=True)
    inventory_file.write_text(
        "version: 1\n" "call_surfaces: []\n" "allowed_adapter_boundaries: []\n",
        encoding="utf-8",
    )

    report = module.run_compliance_checks(
        repo_root=tmp_path, inventory_path=inventory_file
    )
    assert any("missing from inventory" in error for error in report.errors)


def test_run_checks_detects_bypass_invocation(tmp_path: Path) -> None:
    module = _load_compliance_module()
    service_file = tmp_path / "src" / "core" / "services" / "bypass.py"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(
        "async def run(backend, request):\n"
        "    return await backend.chat_completions(request)\n",
        encoding="utf-8",
    )

    inventory_file = tmp_path / "dev" / "routing" / "unified_routing_inventory.yaml"
    inventory_file.parent.mkdir(parents=True, exist_ok=True)
    inventory_file.write_text(
        "version: 1\n"
        "call_surfaces:\n"
        "  - id: bypass\n"
        "    kind: direct\n"
        "    file: src/core/services/bypass.py\n"
        "    function: run\n"
        "    call: backend.chat_completions\n"
        "allowed_adapter_boundaries: []\n",
        encoding="utf-8",
    )

    report = module.run_compliance_checks(
        repo_root=tmp_path, inventory_path=inventory_file
    )
    assert any("bypass" in error.lower() for error in report.errors)


def test_run_checks_detects_bypass_outside_core_services_scope(tmp_path: Path) -> None:
    module = _load_compliance_module()
    handler_file = tmp_path / "src" / "codebuff" / "handlers" / "bypass.py"
    handler_file.parent.mkdir(parents=True, exist_ok=True)
    handler_file.write_text(
        "async def run(backend, request):\n"
        "    return await backend.chat_completions(request)\n",
        encoding="utf-8",
    )

    inventory_file = tmp_path / "dev" / "routing" / "unified_routing_inventory.yaml"
    inventory_file.parent.mkdir(parents=True, exist_ok=True)
    inventory_file.write_text(
        "version: 1\n"
        "scan_roots:\n"
        "  - src/codebuff/handlers\n"
        "call_surfaces: []\n"
        "allowed_adapter_boundaries: []\n",
        encoding="utf-8",
    )

    report = module.run_compliance_checks(
        repo_root=tmp_path, inventory_path=inventory_file
    )
    assert any("bypass" in error.lower() for error in report.errors)


def test_run_checks_detects_call_completion_bypass_invocation(tmp_path: Path) -> None:
    module = _load_compliance_module()
    service_file = tmp_path / "src" / "core" / "services" / "bypass.py"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(
        "async def run(backend, request):\n"
        "    return await backend.call_completion(request)\n",
        encoding="utf-8",
    )

    inventory_file = tmp_path / "dev" / "routing" / "unified_routing_inventory.yaml"
    inventory_file.parent.mkdir(parents=True, exist_ok=True)
    inventory_file.write_text(
        "version: 1\n" "call_surfaces: []\n" "allowed_adapter_boundaries: []\n",
        encoding="utf-8",
    )

    report = module.run_compliance_checks(
        repo_root=tmp_path, inventory_path=inventory_file
    )
    assert any("bypass" in error.lower() for error in report.errors)


def test_run_checks_allows_internal_call_completion_delegate(tmp_path: Path) -> None:
    module = _load_compliance_module()
    service_file = tmp_path / "src" / "core" / "services" / "delegate.py"
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(
        "class Delegate:\n"
        "    async def call_completion(self, request):\n"
        "        return request\n"
        "    async def chat_completions(self, request):\n"
        "        return await self.call_completion(request)\n",
        encoding="utf-8",
    )

    inventory_file = tmp_path / "dev" / "routing" / "unified_routing_inventory.yaml"
    inventory_file.parent.mkdir(parents=True, exist_ok=True)
    inventory_file.write_text(
        "version: 1\n" "call_surfaces: []\n" "allowed_adapter_boundaries: []\n",
        encoding="utf-8",
    )

    report = module.run_compliance_checks(
        repo_root=tmp_path, inventory_path=inventory_file
    )
    assert not any("bypass" in error.lower() for error in report.errors)


def test_live_repo_inventory_contract_has_no_drift_or_bypass() -> None:
    module = _load_compliance_module()
    report = module.run_compliance_checks(
        repo_root=REPO_ROOT, inventory_path=INVENTORY_PATH
    )

    assert report.errors == []
    assert report.bypass_keys == set()
    assert report.discovered_keys == report.inventory_direct_keys
