"""Regression tests for Gemini API key environment variable loading.

Covers:
1. Windows persistent env fallback for GEMINI_API_KEY
2. Numbered Gemini keys (GEMINI_API_KEY_1..N) creating backend instances
3. Precedence: numbered keys take priority; base key suppressed when numbered keys exist
4. Single-instance scenarios (only GEMINI_API_KEY, or only GEMINI_API_KEY_1)
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

from src.core.common.env_utils import get_env_value_with_windows_persistent_fallback
from src.core.config.app_config import AppConfig
from src.core.config.env.from_env_part3 import _has_numbered_env_variants
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.config.sources.backend_instances import BackendInstanceEnvSource

# ── 1. Windows persistent env fallback for GEMINI_API_KEY ───────────────────


class TestGeminiWindowsPersistentFallback:
    """Ensure Gemini base key reads from the Windows persistent registry
    when the process-level snapshot is stale."""

    def test_gemini_uses_persistent_fallback_when_process_is_stale(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

        stale_key = "old-leaked-gemini-key"
        fresh_key = "fresh-gemini-key-from-registry"

        class _Key:
            def __init__(self, hive: str, subkey: str) -> None:
                self.hive = hive
                self.subkey = subkey

            def __enter__(self) -> _Key:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        persistent_values: dict[tuple[str, str, str], str] = {
            ("HKCU", r"Environment", "GEMINI_API_KEY"): fresh_key,
        }

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            HKEY_LOCAL_MACHINE="HKLM",
            OpenKey=lambda hive, subkey: _Key(hive, subkey),
            QueryValueEx=lambda key, name: (
                persistent_values[(key.hive, key.subkey, name)],
                1,
            ),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

        # Simulate process env being stale
        env = {"GEMINI_API_KEY": stale_key}
        value, source = get_env_value_with_windows_persistent_fallback(
            "GEMINI_API_KEY", environ=env
        )
        assert value == fresh_key
        assert source == "windows-user"

    def test_gemini_fallback_returns_process_value_when_matching(
        self, monkeypatch
    ) -> None:
        """When process and registry agree, source should be 'process'."""
        monkeypatch.setattr(sys, "platform", "win32")

        same_key = "same-gemini-key"

        class _Key:
            def __init__(self, hive: str, subkey: str) -> None:
                self.hive = hive
                self.subkey = subkey

            def __enter__(self) -> _Key:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            HKEY_LOCAL_MACHINE="HKLM",
            OpenKey=lambda hive, subkey: _Key(hive, subkey),
            QueryValueEx=lambda key, name: (same_key, 1),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

        env = {"GEMINI_API_KEY": same_key}
        value, source = get_env_value_with_windows_persistent_fallback(
            "GEMINI_API_KEY", environ=env
        )
        assert value == same_key
        assert source == "process"

    def test_gemini_reports_missing_when_unset(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

        class _Key:
            def __init__(self, hive: str, subkey: str) -> None:
                self.hive = hive
                self.subkey = subkey

            def __enter__(self) -> _Key:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            HKEY_LOCAL_MACHINE="HKLM",
            OpenKey=lambda hive, subkey: _Key(hive, subkey),
            QueryValueEx=lambda key, name: (_ for _ in ()).throw(OSError("missing")),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

        value, source = get_env_value_with_windows_persistent_fallback(
            "GEMINI_API_KEY", environ={}
        )
        assert value is None
        assert source == "missing"


# ── 2. _has_numbered_env_variants helper ────────────────────────────────────


class TestHasNumberedEnvVariants:
    def test_no_variants_returns_false(self) -> None:
        assert _has_numbered_env_variants({}, "GEMINI_API_KEY") is False

    def test_empty_string_does_not_count(self) -> None:
        env = {"GEMINI_API_KEY_1": "", "GEMINI_API_KEY_2": "   "}
        assert _has_numbered_env_variants(env, "GEMINI_API_KEY") is False

    def test_variant_1_returns_true(self) -> None:
        env = {"GEMINI_API_KEY_1": "val"}
        assert _has_numbered_env_variants(env, "GEMINI_API_KEY") is True

    def test_variant_5_returns_true(self) -> None:
        env = {"GEMINI_API_KEY_5": "val"}
        assert _has_numbered_env_variants(env, "GEMINI_API_KEY") is True


# ── 3. BackendInstanceEnvSource discovers Gemini numbered keys ──────────────


class TestGeminiInstanceEnvDiscovery:
    def test_discovers_gemini_1(self) -> None:
        env = {
            "GEMINI_API_KEY_1": "gemini-key-one",
        }
        source = BackendInstanceEnvSource()
        resolution = ParameterResolution()

        with patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ):
            result = source.load(
                env, existing_instance_names=set(), resolution=resolution
            )

        backends = result.get("backends", {})
        assert isinstance(backends, dict)
        assert "gemini.1" in backends
        assert backends["gemini.1"]["api_key"] == "gemini-key-one"
        assert backends["gemini.1"]["connector"] == "gemini"

    def test_discovers_multiple_gemini_keys(self) -> None:
        env = {
            "GEMINI_API_KEY_1": "key-1",
            "GEMINI_API_KEY_2": "key-2",
            "GEMINI_API_KEY_3": "key-3",
        }
        source = BackendInstanceEnvSource()
        resolution = ParameterResolution()

        with patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ):
            result = source.load(
                env, existing_instance_names=set(), resolution=resolution
            )

        backends = result.get("backends", {})
        assert "gemini.1" in backends
        assert "gemini.2" in backends
        assert "gemini.3" in backends
        assert backends["gemini.1"]["api_key"] == "key-1"
        assert backends["gemini.2"]["api_key"] == "key-2"
        assert backends["gemini.3"]["api_key"] == "key-3"

    def test_resolution_tracks_gemini_instance_origin(self) -> None:
        env = {"GEMINI_API_KEY_2": "key-two"}
        source = BackendInstanceEnvSource()
        resolution = ParameterResolution()

        with patch(
            "src.core.config.sources.backend_instances.backend_registry.get_registered_backends",
            return_value=["gemini"],
        ):
            source.load(env, existing_instance_names=set(), resolution=resolution)

        report = {entry.name: entry for entry in resolution.build_report(AppConfig())}
        entry = report['backends["gemini.2"].api_key']
        assert entry.source is ParameterSource.ENVIRONMENT
        assert entry.origin == "GEMINI_API_KEY_2"


# ── 4. Full AppConfig integration: numbered keys create instances ───────────


class TestGeminiAppConfigNumberedInstances:
    def test_single_numbered_key_creates_one_instance(self) -> None:
        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY_1": "fresh-key-1",
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
            cfg = AppConfig.from_env(environ=env)

        instance = cfg.backends.get("gemini.1")
        assert instance is not None
        assert instance.api_key == "fresh-key-1"

    def test_multiple_numbered_keys_create_multiple_instances(self) -> None:
        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY_1": "fresh-key-1",
            "GEMINI_API_KEY_2": "fresh-key-2",
            "GEMINI_API_KEY_3": "fresh-key-3",
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
            cfg = AppConfig.from_env(environ=env)

        assert cfg.backends.get("gemini.1") is not None
        assert cfg.backends.get("gemini.2") is not None
        assert cfg.backends.get("gemini.3") is not None
        assert cfg.backends.get("gemini.1").api_key == "fresh-key-1"
        assert cfg.backends.get("gemini.2").api_key == "fresh-key-2"
        assert cfg.backends.get("gemini.3").api_key == "fresh-key-3"

    def test_numbered_keys_take_precedence_over_base_key(self) -> None:
        """When numbered variants exist, base GEMINI_API_KEY must not bind
        to the plain 'gemini' backend. This prevents stale/leaked base keys
        from being used."""
        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY": "old-leaked-key",
            "GEMINI_API_KEY_1": "fresh-key-1",
            "GEMINI_API_KEY_2": "fresh-key-2",
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
            cfg = AppConfig.from_env(environ=env)

        base_cfg = cfg.backends.lookup("gemini")
        instance_1 = cfg.backends.lookup("gemini.1")
        instance_2 = cfg.backends.lookup("gemini.2")

        # Instances must have the numbered keys
        assert instance_1 is not None
        assert instance_1.api_key == "fresh-key-1"
        assert instance_2 is not None
        assert instance_2.api_key == "fresh-key-2"

        # Base gemini must NOT pick up the stale leaked key
        if base_cfg is not None:
            assert base_cfg.api_key != "old-leaked-key", (
                "Plain 'gemini' backend must not use base GEMINI_API_KEY "
                "when numbered variants exist"
            )

    def test_only_base_key_creates_single_instance(self) -> None:
        """When only GEMINI_API_KEY is set (no numbered keys), one
        plain 'gemini' instance should be created."""
        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY": "only-base-key",
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
            cfg = AppConfig.from_env(environ=env)

        base_cfg = cfg.backends.lookup("gemini")
        assert base_cfg is not None
        assert base_cfg.api_key == "only-base-key"

    def test_only_gemini_api_key_1_creates_single_instance(self) -> None:
        """When only GEMINI_API_KEY_1 is set, only gemini.1 instance."""
        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY_1": "sole-numbered-key",
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
            cfg = AppConfig.from_env(environ=env)

        instance_1 = cfg.backends.lookup("gemini.1")
        base_cfg = cfg.backends.lookup("gemini")

        assert instance_1 is not None
        assert instance_1.api_key == "sole-numbered-key"
        # Base should not have a key
        assert base_cfg is None or base_cfg.api_key is None

    def test_gemini_key_gap_in_sequence_still_discovers_noncontiguous(self) -> None:
        """GEMINI_API_KEY_1 and GEMINI_API_KEY_3 without _2 should
        still produce gemini.1 and gemini.3 (non-contiguous scan)."""
        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY_1": "key-1",
            "GEMINI_API_KEY_3": "key-3",
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
            cfg = AppConfig.from_env(environ=env)

        instance_1 = cfg.backends.lookup("gemini.1")
        instance_2 = cfg.backends.lookup("gemini.2")
        instance_3 = cfg.backends.lookup("gemini.3")

        assert instance_1 is not None
        assert instance_1.api_key == "key-1"
        assert instance_2 is None
        assert instance_3 is not None
        assert instance_3.api_key == "key-3"


# ── 5. End-to-end: Windows stale env + numbered keys ────────────────────────


class TestGeminiStaleEnvEndToEnd:
    """Simulate the exact bug scenario: stale process GEMINI_API_KEY,
    fresh numbered keys in Windows registry."""

    def test_stale_base_key_ignored_when_numbered_exist(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

        old_leaked_key = "old-leaked-gemini-key-AIzaSy"
        fresh_key_1 = "fresh-gemini-key-1-never-used"
        fresh_key_2 = "fresh-gemini-key-2-never-used"

        class _Key:
            def __init__(self, hive: str, subkey: str) -> None:
                self.hive = hive
                self.subkey = subkey

            def __enter__(self) -> _Key:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        def _query(key: _Key, name: str) -> tuple[str, int]:
            if name == "GEMINI_API_KEY":
                return (old_leaked_key, 1)
            raise OSError("not found")

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER="HKCU",
            HKEY_LOCAL_MACHINE="HKLM",
            OpenKey=lambda hive, subkey: _Key(hive, subkey),
            QueryValueEx=_query,
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

        env = {
            "LLM_BACKEND": "gemini",
            "GEMINI_API_KEY": old_leaked_key,
            "GEMINI_API_KEY_1": fresh_key_1,
            "GEMINI_API_KEY_2": fresh_key_2,
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
            cfg = AppConfig.from_env(environ=env)

        instance_1 = cfg.backends.lookup("gemini.1")
        instance_2 = cfg.backends.lookup("gemini.2")
        base_cfg = cfg.backends.lookup("gemini")

        assert instance_1 is not None
        assert instance_1.api_key == fresh_key_1
        assert instance_2 is not None
        assert instance_2.api_key == fresh_key_2

        if base_cfg is not None:
            assert (
                base_cfg.api_key != old_leaked_key
            ), "Base gemini must not use stale leaked key when numbered variants exist"
