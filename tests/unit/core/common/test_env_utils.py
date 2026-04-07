from __future__ import annotations

import sys
from types import SimpleNamespace

from src.core.common.env_utils import get_env_value_with_windows_persistent_fallback


def test_windows_persistent_env_fallback_prefers_user_value_when_process_is_stale(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    values = {
        ("HKCU", r"Environment", "ZAI_API_KEY"): "fresh-user-key",
        (
            "HKLM",
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            "ZAI_API_KEY",
        ): "machine-key",
    }

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
        QueryValueEx=lambda key, name: (values[(key.hive, key.subkey, name)], 1),
    )

    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    value, source = get_env_value_with_windows_persistent_fallback(
        "ZAI_API_KEY", environ={"ZAI_API_KEY": "stale-process-key"}
    )

    assert value == "fresh-user-key"
    assert source == "windows-user"


def test_non_windows_env_fallback_uses_process_value(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    value, source = get_env_value_with_windows_persistent_fallback(
        "ZAI_API_KEY", environ={"ZAI_API_KEY": "process-key"}
    )

    assert value == "process-key"
    assert source == "process"


def test_windows_persistent_env_fallback_uses_machine_when_user_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    class _Key:
        def __init__(self, hive: str, subkey: str) -> None:
            self.hive = hive
            self.subkey = subkey

        def __enter__(self) -> _Key:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _query_value(key: _Key, name: str) -> tuple[str, int]:
        if key.hive == "HKCU":
            raise OSError("missing")
        assert name == "ZAI_API_KEY"
        return ("machine-key", 1)

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        HKEY_LOCAL_MACHINE="HKLM",
        OpenKey=lambda hive, subkey: _Key(hive, subkey),
        QueryValueEx=_query_value,
    )

    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    value, source = get_env_value_with_windows_persistent_fallback(
        "ZAI_API_KEY", environ={"ZAI_API_KEY": "stale-process-key"}
    )

    assert value == "machine-key"
    assert source == "windows-machine"


def test_windows_persistent_env_fallback_keeps_process_when_values_match(
    monkeypatch,
) -> None:
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
        QueryValueEx=lambda key, name: ("same-key", 1),
    )

    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    value, source = get_env_value_with_windows_persistent_fallback(
        "ZAI_API_KEY", environ={"ZAI_API_KEY": "same-key"}
    )

    assert value == "same-key"
    assert source == "process"


def test_windows_persistent_env_fallback_reports_missing_when_unset(
    monkeypatch,
) -> None:
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
        "ZAI_API_KEY", environ={}
    )

    assert value is None
    assert source == "missing"
