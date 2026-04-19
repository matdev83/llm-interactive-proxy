"""Unit tests for ACP subprocess identity (PID reuse hardening)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.connectors.acp_core import acp_subprocess_identity as sid_mod
from src.connectors.acp_core.acp_subprocess_identity import (
    capture_acp_subprocess_identity,
    stale_kill_still_same_os_process,
)
from src.connectors.acp_core.types import AcpSubprocessIdentity


@pytest.fixture
def mock_popen() -> MagicMock:
    proc = MagicMock()
    proc.pid = 9001
    proc.poll.return_value = None
    return proc


def test_capture_returns_none_when_psutil_unavailable(mock_popen: MagicMock) -> None:
    with patch.object(sid_mod, "_psutil", None):
        assert capture_acp_subprocess_identity(mock_popen, ["gemini"]) is None


def test_capture_returns_none_for_non_integer_pid() -> None:
    proc = MagicMock()
    proc.pid = MagicMock()
    with patch.object(sid_mod, "_psutil", MagicMock()):
        assert capture_acp_subprocess_identity(proc, ["gemini"]) is None


def test_capture_success(mock_popen: MagicMock) -> None:
    mock_psutil = MagicMock()
    mock_proc = MagicMock()
    mock_proc.create_time.return_value = 12345.5
    mock_proc.exe.return_value = r"C:\Tools\gemini.exe"
    mock_psutil.Process.return_value = mock_proc
    mock_psutil.Error = Exception
    mock_psutil.AccessDenied = Exception

    with patch.object(sid_mod, "_psutil", mock_psutil):
        ident = capture_acp_subprocess_identity(mock_popen, [r"C:\Tools\gemini.exe"])
    assert ident is not None
    assert ident.pid == 9001
    assert ident.create_time == 12345.5
    assert ident.exe_key


def test_stale_kill_rejects_create_time_mismatch(mock_popen: MagicMock) -> None:
    ident = AcpSubprocessIdentity(pid=9001, create_time=1.0, exe_key="a.exe")
    mock_psutil = MagicMock()
    mock_os = MagicMock()
    mock_os.create_time.return_value = 99.0
    mock_psutil.Process.return_value = mock_os
    mock_psutil.NoSuchProcess = Exception
    mock_psutil.Error = Exception

    with patch.object(sid_mod, "_psutil", mock_psutil):
        assert stale_kill_still_same_os_process(mock_popen, ident) is False


def test_stale_kill_accepts_matching_identity(mock_popen: MagicMock) -> None:
    ident = AcpSubprocessIdentity(pid=9001, create_time=10.0, exe_key="")
    mock_psutil = MagicMock()
    mock_os = MagicMock()
    mock_os.create_time.return_value = 10.05
    mock_psutil.Process.return_value = mock_os
    mock_psutil.NoSuchProcess = Exception
    mock_psutil.Error = Exception

    with patch.object(sid_mod, "_psutil", mock_psutil):
        assert stale_kill_still_same_os_process(mock_popen, ident) is True


def test_stale_kill_rejects_exe_mismatch(mock_popen: MagicMock) -> None:
    ident = AcpSubprocessIdentity(pid=9001, create_time=10.0, exe_key="a\\gemini.exe")
    mock_psutil = MagicMock()
    mock_os = MagicMock()
    mock_os.create_time.return_value = 10.0
    mock_os.exe.return_value = r"C:\Other\notepad.exe"
    mock_psutil.Process.return_value = mock_os
    mock_psutil.NoSuchProcess = Exception
    mock_psutil.Error = Exception

    with patch.object(sid_mod, "_psutil", mock_psutil):
        assert stale_kill_still_same_os_process(mock_popen, ident) is False


def test_stale_kill_false_when_identity_none(mock_popen: MagicMock) -> None:
    assert stale_kill_still_same_os_process(mock_popen, None) is False


def test_stale_kill_true_when_psutil_unavailable_but_identity_present(
    mock_popen: MagicMock,
) -> None:
    ident = AcpSubprocessIdentity(pid=9001, create_time=1.0, exe_key="a.exe")
    with patch.object(sid_mod, "_psutil", None):
        assert stale_kill_still_same_os_process(mock_popen, ident) is True
