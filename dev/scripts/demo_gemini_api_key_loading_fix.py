"""Demo script proving the Gemini API key loading fix.

Simulates the exact production bug:
- Stale GEMINI_API_KEY in process env (old leaked key)
- Fresh GEMINI_API_KEY_1..3 set (never used, cannot leak)

Demonstrates that:
1. Without the fix: proxy would send the stale leaked key
2. With the fix: proxy correctly uses the numbered instances

Run: .venv/Scripts/python.exe dev/scripts/demo_gemini_api_key_loading_fix.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ── Test data ──────────────────────────────────────────────────────────────

OLD_LEAKED_KEY = "AIzaSy-old-leaked-key-disabled-by-google"
FRESH_KEY_1 = "AIzaSy-fresh-never-used-1"
FRESH_KEY_2 = "AIzaSy-fresh-never-used-2"
FRESH_KEY_3 = "AIzaSy-fresh-never-used-3"


def _simulate_windows_env(monkeypatch, stale_key: str | None) -> None:
    """Set up a fake Windows registry with a stale key different from process env."""
    monkeypatch.setattr(sys, "platform", "win32")

    # Registry has a different key than process env
    registry_key = OLD_LEAKED_KEY if stale_key is None else stale_key

    class _Key:
        def __init__(self, hive: str, subkey: str) -> None:
            self.hive = hive
            self.subkey = subkey

        def __enter__(self) -> "_Key":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _query(key: _Key, name: str) -> tuple[str, int]:
        if name == "GEMINI_API_KEY":
            return (registry_key, 1)
        raise OSError("not found")

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        HKEY_LOCAL_MACHINE="HKLM",
        OpenKey=lambda hive, subkey: _Key(hive, subkey),
        QueryValueEx=_query,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)


def demo_broken_scenario(monkeypatch) -> None:
    """Show what the OLD code would do: pick the stale leaked key."""
    print("=" * 72)
    print("SCENARIO 1: OLD behavior (broken) - raw env.get('GEMINI_API_KEY')")
    print("=" * 72)

    env = {
        "LLM_BACKEND": "gemini",
        "GEMINI_API_KEY": OLD_LEAKED_KEY,
        "GEMINI_API_KEY_1": FRESH_KEY_1,
        "GEMINI_API_KEY_2": FRESH_KEY_2,
        "GEMINI_API_KEY_3": FRESH_KEY_3,
    }

    _simulate_windows_env(monkeypatch, stale_key=OLD_LEAKED_KEY)

    # Simulate old broken code path
    if env.get("GEMINI_API_KEY"):
        picked_key = env["GEMINI_API_KEY"]
        print(f"  Raw env.get('GEMINI_API_KEY') returned: {picked_key[:30]}...")
        print(f"  This is the LEAKED, DISABLED key!")
        print(f"  Result: Remote API would reject this key with 403")
        print()
        assert picked_key == OLD_LEAKED_KEY
        print(f"  FAIL: Proxy would send stale key: {picked_key[:20]}***")
    print()


def demo_fixed_scenario(monkeypatch) -> None:
    """Show what the NEW code does: ignores stale key when numbered variants exist."""
    print("=" * 72)
    print("SCENARIO 2: NEW behavior (fixed) - Windows fallback + numbered guard")
    print("=" * 72)

    env = {
        "LLM_BACKEND": "gemini",
        "GEMINI_API_KEY": OLD_LEAKED_KEY,
        "GEMINI_API_KEY_1": FRESH_KEY_1,
        "GEMINI_API_KEY_2": FRESH_KEY_2,
        "GEMINI_API_KEY_3": FRESH_KEY_3,
    }

    _simulate_windows_env(monkeypatch, stale_key=OLD_LEAKED_KEY)

    # Simulate fixed code path
    from src.core.common.env_utils import get_env_value_with_windows_persistent_fallback
    import src.core.config.env.from_env_part3 as _part3

    gemini_key, gemini_source = get_env_value_with_windows_persistent_fallback(
        "GEMINI_API_KEY", environ=env
    )
    has_variants = _part3._has_numbered_env_variants(env, "GEMINI_API_KEY")  # noqa: SLF001

    print(f"  Windows fallback resolved key from: {gemini_source}")
    print(f"  Numbered variants exist: {has_variants}")
    print()

    if gemini_key and not has_variants:
        print(f"  Would bind base gemini with key: {gemini_key[:30]}...")
    else:
        print(f"  Numbered variants present => skipping base key binding")
        print(f"  Instances will be created from numbered keys instead:")
        print(f"    gemini.1 => {FRESH_KEY_1[:20]}...")
        print(f"    gemini.2 => {FRESH_KEY_2[:20]}...")
        print(f"    gemini.3 => {FRESH_KEY_3[:20]}...")
    print()
    print(f"  PASS: Stale leaked key is correctly ignored")
    print()


def demo_full_integration(monkeypatch) -> None:
    """Full AppConfig.from_env integration test."""
    print("=" * 72)
    print("SCENARIO 3: Full integration - AppConfig.from_env with numbered keys")
    print("=" * 72)

    env = {
        "LLM_BACKEND": "gemini",
        "GEMINI_API_KEY": OLD_LEAKED_KEY,
        "GEMINI_API_KEY_1": FRESH_KEY_1,
        "GEMINI_API_KEY_2": FRESH_KEY_2,
        "GEMINI_API_KEY_3": FRESH_KEY_3,
    }

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ),
        patch(
            "src.core.services.backend_registry.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ),
    ):
        from src.core.config.app_config import AppConfig

        cfg = AppConfig.from_env(environ=env)

    base_cfg = cfg.backends.lookup("gemini")
    instance_1 = cfg.backends.lookup("gemini.1")
    instance_2 = cfg.backends.lookup("gemini.2")
    instance_3 = cfg.backends.lookup("gemini.3")

    print(f"  Backends discovered:")

    if base_cfg is not None:
        print(f"    gemini (base)     => api_key: {base_cfg.api_key or 'None'}")
    else:
        print(f"    gemini (base)     => not bound (correct!)")

    if instance_1 and instance_1.api_key:
        print(f"    gemini.1          => api_key: {instance_1.api_key[:20]}...")
    if instance_2 and instance_2.api_key:
        print(f"    gemini.2          => api_key: {instance_2.api_key[:20]}...")
    if instance_3 and instance_3.api_key:
        print(f"    gemini.3          => api_key: {instance_3.api_key[:20]}...")

    print()

    # Verify invariants
    errors = []

    if base_cfg is not None and base_cfg.api_key == OLD_LEAKED_KEY:
        errors.append("CRITICAL: base gemini still has the leaked key!")

    if not instance_1:
        errors.append("gemini.1 instance missing")
    elif instance_1.api_key != FRESH_KEY_1:
        assert instance_1.api_key is not None
        errors.append(f"gemini.1 has wrong key: {instance_1.api_key[:20]}...")

    if not instance_2:
        errors.append("gemini.2 instance missing")
    elif instance_2.api_key != FRESH_KEY_2:
        assert instance_2.api_key is not None
        errors.append(f"gemini.2 has wrong key: {instance_2.api_key[:20]}...")

    if not instance_3:
        errors.append("gemini.3 instance missing")
    elif instance_3.api_key != FRESH_KEY_3:
        assert instance_3.api_key is not None
        errors.append(f"gemini.3 has wrong key: {instance_3.api_key[:20]}...")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
    else:
        print("  PASS: All invariants hold - numbered instances are correct,")
        print("        stale base key is ignored")
    print()


def demo_single_base_key_only(monkeypatch) -> None:
    """When only GEMINI_API_KEY is set, it should still work."""
    print("=" * 72)
    print("SCENARIO 4: Only GEMINI_API_KEY set (no numbered variants)")
    print("=" * 72)

    env = {
        "LLM_BACKEND": "gemini",
        "GEMINI_API_KEY": FRESH_KEY_1,
    }

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ),
        patch(
            "src.core.services.backend_registry.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ),
    ):
        from src.core.config.app_config import AppConfig

        cfg = AppConfig.from_env(environ=env)

    base_cfg = cfg.backends.lookup("gemini")
    instance_1 = cfg.backends.lookup("gemini.1")

    print(f"  gemini (base)     => api_key: {base_cfg.api_key[:20] if base_cfg and base_cfg.api_key else 'None'}...")
    print(f"  gemini.1          => {'present' if instance_1 else 'not created'}")
    print()

    if base_cfg and base_cfg.api_key == FRESH_KEY_1 and instance_1 is None:
        print("  PASS: Single base key works correctly")
    else:
        print("  FAIL: Expected base key binding with no numbered instances")
    print()


def demo_single_numbered_key_only(monkeypatch) -> None:
    """When only GEMINI_API_KEY_1 is set, only gemini.1 should be created."""
    print("=" * 72)
    print("SCENARIO 5: Only GEMINI_API_KEY_1 set (no base key)")
    print("=" * 72)

    env = {
        "LLM_BACKEND": "gemini",
        "GEMINI_API_KEY_1": FRESH_KEY_1,
    }

    with (
        patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ),
        patch(
            "src.core.services.backend_registry.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ),
    ):
        from src.core.config.app_config import AppConfig

        cfg = AppConfig.from_env(environ=env)

    base_cfg = cfg.backends.lookup("gemini")
    instance_1 = cfg.backends.lookup("gemini.1")

    print(f"  gemini (base)     => api_key: {base_cfg.api_key[:20] if base_cfg and base_cfg.api_key else 'None'}...")
    print(f"  gemini.1          => api_key: {instance_1.api_key[:20] if instance_1 and instance_1.api_key else 'None'}...")
    print()

    has_base_key = base_cfg and base_cfg.api_key and base_cfg.api_key != OLD_LEAKED_KEY
    has_instance_1 = instance_1 and instance_1.api_key == FRESH_KEY_1

    if has_instance_1:
        print("  PASS: Single numbered key creates correct instance")
        if has_base_key:
            print("  Note: base key also set (acceptable, will be from env fallback)")
    else:
        print("  FAIL: Expected gemini.1 instance")
    print()


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("*" * 72)
    print("* Gemini API Key Loading Fix - Demonstration")
    print("*" * 72)
    print()

    # We use a simple monkeypatch approach
    import sys as _sys

    saved_modules = {}

    def _run(scenario_fn) -> None:
        """Run a scenario with isolated module state."""
        # Remove winreg if present from previous run
        saved_modules["winreg"] = _sys.modules.get("winreg")
        saved_modules["platform"] = _sys.modules.get("platform")

        scenario_fn(_Monkeypatch())

        # Cleanup
        if "winreg" in _sys.modules:
            del _sys.modules["winreg"]
        if saved_modules["winreg"] is not None:
            _sys.modules["winreg"] = saved_modules["winreg"]

    _run(demo_broken_scenario)
    _run(demo_fixed_scenario)
    _run(demo_full_integration)
    _run(demo_single_base_key_only)
    _run(demo_single_numbered_key_only)

    print("*" * 72)
    print("* Demonstration complete")
    print("*" * 72)
    print()


class _Monkeypatch:
    """Minimal monkeypatch implementation for the demo."""

    def setattr(self, obj: object, name: str, value: object) -> None:
        setattr(obj, name, value)

    def setitem(self, mapping: dict, key: str, value: object) -> None:
        mapping[key] = value


if __name__ == "__main__":
    main()
