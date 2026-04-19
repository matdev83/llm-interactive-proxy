"""Capture and verify OS identity of pooled ACP subprocesses (PID reuse hardening)."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.connectors.acp_core.types import AcpSubprocessIdentity

if TYPE_CHECKING:
    import subprocess

_psutil: Any
try:
    import psutil as _psutil
except ImportError:  # pragma: no cover - exercised when psutil missing from env
    _psutil = None

logger = logging.getLogger(__name__)

_CREATE_TIME_EPSILON = 0.75


def _normalize_exe_key(raw: str) -> str:
    if not raw:
        return ""
    candidate = raw.strip().strip('"')
    if not candidate:
        return ""
    try:
        resolved = str(Path(candidate).resolve())
        return os.path.normcase(resolved)
    except OSError:
        return os.path.normcase(candidate)


def capture_acp_subprocess_identity(
    process: subprocess.Popen[bytes],
    cmd: Sequence[str],
) -> AcpSubprocessIdentity | None:
    """Snapshot pid, start time, and executable path for later stale-kill verification."""
    if _psutil is None:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "psutil is not installed; ACP idle-kill cannot fingerprint the child "
                "process (PID reuse checks disabled). Install psutil for full protection."
            )
        return None

    pid = getattr(process, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        p = _psutil.Process(pid)
        create_time = float(p.create_time())
        exe_guess = ""
        with contextlib.suppress(_psutil.AccessDenied, _psutil.Error):
            exe_guess = p.exe()
        if not exe_guess and cmd:
            exe_guess = str(cmd[0])
        return AcpSubprocessIdentity(
            pid=pid,
            create_time=create_time,
            exe_key=_normalize_exe_key(exe_guess),
        )
    except (_psutil.Error, NotImplementedError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Could not capture ACP subprocess identity for pid=%s",
                pid,
                exc_info=True,
            )
        return None


def stale_kill_still_same_os_process(
    process: subprocess.Popen[bytes],
    identity: AcpSubprocessIdentity | None,
) -> bool:
    """Return True if ``process`` is still the same OS process as ``identity``."""
    if identity is None:
        return False
    if process.poll() is not None:
        return False
    cur_pid = getattr(process, "pid", None)
    if not isinstance(cur_pid, int) or cur_pid != identity.pid:
        return False

    if _psutil is None:
        return False

    try:
        current = _psutil.Process(identity.pid)
    except _psutil.NoSuchProcess:
        return False
    except _psutil.Error:
        return False

    try:
        cur_ct = float(current.create_time())
    except _psutil.Error:
        return False

    if abs(cur_ct - identity.create_time) > _CREATE_TIME_EPSILON:
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Stale ACP kill skipped: process start time mismatch (pid=%s)",
                identity.pid,
            )
        return False

    if identity.exe_key:
        cur_exe = ""
        with contextlib.suppress(_psutil.AccessDenied, _psutil.Error):
            cur_exe = _normalize_exe_key(current.exe())
        if cur_exe and cur_exe != identity.exe_key:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Stale ACP kill skipped: executable path mismatch for pid=%s",
                    identity.pid,
                )
            return False

    return True
