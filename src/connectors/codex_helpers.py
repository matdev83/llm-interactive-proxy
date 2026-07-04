"""Pure helpers for the OpenAI Codex App Server backend.

Log-safe label helpers, executable resolution, the ``codex app-server --stdio``
command builder, model-prefix / reasoning-effort mappers, the approval-decision
function, and the approval-summary sanitizer. Stateless and free of any
subprocess or runtime state so they can be unit-tested in isolation.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Server-initiated JSON-RPC request methods that this headless proxy auto-accepts.
# ``item/permissions/requestApproval`` is folded in here but builds a different
# (echoed permissions) result; every other method fails closed via ``decline``.
_CODEX_AUTO_ACCEPT_APPROVAL_METHODS: frozenset[str] = frozenset(
    {
        "execCommandApproval",
        "applyPatchApproval",
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
    }
)


def _command_basename(command: str | None) -> str:
    """Return a short, log-safe command label (first token's basename)."""

    if not command:
        return "<command>"
    stripped = command.strip()
    if not stripped:
        return "<command>"
    first = stripped.split()[0]
    if not first:
        return "<command>"
    base = os.path.basename(first)
    return base or first


def _cwd_basename(cwd: str | None) -> str:
    """Return a short, log-safe label for a workspace directory."""

    if not cwd:
        return "<cwd>"
    name = Path(cwd).name
    return name or cwd


def _resolve_candidate(raw: str) -> str | None:
    """Resolve a single candidate executable.

    A path that points to an existing file is returned as its resolved absolute
    path; any other non-empty string is resolved via ``shutil.which``. Returns
    ``None`` for empty input or when nothing usable is found.
    """

    s = raw.strip()
    if not s:
        return None
    p = Path(s)
    if p.is_file():
        try:
            return str(p.resolve())
        except (OSError, RuntimeError):
            return None
    return shutil.which(s)


def candidate_codex_executables(configured: str | None) -> list[str]:
    """Ordered, de-duplicated codex executable candidates (cross-platform).

    Order: ``configured`` (instance config), ``CODEX_BIN`` env, then PATH
    lookups (``codex``, ``codex.cmd``, ``codex.exe``) and standard npm-global
    locations derived from env vars / ``Path.home()``. No hardcoded personal
    paths: every entry is sourced from the ``configured`` argument, an
    environment variable, ``shutil.which``, or ``Path.home()``.

    De-duplicated by resolved real path (case-insensitive) so the same binary
    surfaced through multiple sources (e.g. ``configured`` and ``which``) only
    appears once and is probed once.
    """

    raw: list[str] = []

    if configured:
        resolved = _resolve_candidate(configured)
        if resolved:
            raw.append(resolved)

    env_bin = os.environ.get("CODEX_BIN", "").strip()
    if env_bin:
        resolved = _resolve_candidate(env_bin)
        if resolved:
            raw.append(resolved)

    for name in ("codex", "codex.cmd", "codex.exe"):
        which = shutil.which(name)
        if which:
            raw.append(which)

    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            npm_cmd = os.path.join(appdata, "npm", "codex.cmd")
            if os.path.isfile(npm_cmd):
                raw.append(npm_cmd)
        localappdata = os.environ.get("LOCALAPPDATA", "").strip()
        if localappdata:
            npm_cmd_local = os.path.join(localappdata, "npm", "codex.cmd")
            if os.path.isfile(npm_cmd_local):
                raw.append(npm_cmd_local)
    else:
        home = Path.home()
        for rel in (".local/bin/codex", ".npm-global/bin/codex"):
            candidate = home / rel
            if candidate.is_file():
                try:
                    raw.append(str(candidate.resolve()))
                except (OSError, RuntimeError):
                    raw.append(str(candidate))

    seen: set[str] = set()
    unique: list[str] = []
    for entry in raw:
        # Dedup by real path with OS-appropriate case normalization. Use
        # ``os.path`` (bound to the real OS's path module at import time)
        # instead of ``Path(entry)`` so this loop is robust to ``os.name``
        # being monkeypatched in tests -- ``Path(entry)`` re-dispatches to
        # PosixPath/WindowsPath based on the *current* ``os.name`` and raises
        # NotImplementedError when the two do not match.
        try:
            key = os.path.normcase(os.path.realpath(entry))
        except (OSError, ValueError, RuntimeError):
            key = os.path.normcase(str(entry))
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def resolve_codex_executable(configured: str | None) -> str | None:
    """Resolve the Codex CLI executable for ``subprocess.Popen`` (back-compat).

    Returns the FIRST candidate from :func:`candidate_codex_executables`, or
    ``None`` when no usable executable is found. Kept for existing callers and
    tests; new code should iterate :func:`candidate_codex_executables` and probe
    each candidate to pick a working one (a single ``shutil.which`` hit may be a
    wrapper that already injects the app-server flags).
    """

    candidates = candidate_codex_executables(configured)
    return candidates[0] if candidates else None


def build_codex_app_server_command(
    executable: str,
    *,
    codex_config_overrides: Sequence[str] | None = None,
    app_server_extra_args: Sequence[str] | None = None,
) -> list[str]:
    """Build the ``codex app-server --stdio`` launch command.

    Global flags precede ``app-server``; ``-c k=v`` overrides sit between
    ``app-server`` and ``--stdio``; extra args are appended last. The model is
    passed via ``thread/start``, not a CLI flag.
    """

    cmd: list[str] = [
        executable,
        "--dangerously-bypass-approvals-and-sandbox",
        "--search",
        "app-server",
    ]
    for override in codex_config_overrides or ():
        cmd.extend(["-c", str(override)])
    cmd.append("--stdio")
    for extra in app_server_extra_args or ():
        cmd.append(str(extra))
    return cmd


def strip_openai_model_prefix(model: str) -> str:
    """Strip a leading ``openai/`` vendor prefix; empty/None -> ``""``."""

    if not model:
        return ""
    prefix = "openai/"
    if model.startswith(prefix):
        return model[len(prefix) :]
    return model


def is_auto_model(model: str) -> bool:
    """True when the normalized model is empty or ``auto`` (case-insensitive)."""

    normalized = (model or "").strip().lower()
    return normalized in ("", "auto")


def map_reasoning_effort_to_codex_effort(value: str | None) -> str | None:
    """Normalize an OpenAI ``reasoning_effort`` for Codex ``turn/start.effort``.

    Any non-empty value is forwarded lowercased (e.g. ``low`` / ``medium`` /
    ``high``, and newer values like ``xhigh``); the Codex app-server validates
    it and rejects unsupported values with a ``turn/start`` error. ``None`` or an
    empty string returns ``None`` (effort omitted from ``turn/start``).
    """

    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    return normalized


def sanitize_approval_summary(params: Mapping[str, Any]) -> str:
    """Build a short, secret-free summary of an approval request for logging.

    Includes only the command basename, cwd basename, changed-paths count and
    exit code (when present). Never includes full command args, env, diffs or
    output. Truncated to ~120 chars.
    """

    cmd = _command_basename(params.get("command"))
    cwd = _cwd_basename(params.get("cwd"))
    changes = params.get("changes")
    paths_count = len(changes) if isinstance(changes, list) else 0
    parts: list[str] = [f"cmd={cmd}", f"cwd={cwd}", f"paths={paths_count}"]
    exit_code = params.get("exitCode")
    if exit_code is not None:
        parts.append(f"exit={exit_code}")
    summary = " ".join(parts)
    if len(summary) > 120:
        summary = summary[:117] + "..."
    return summary


def build_turn_interrupt_payload(thread_id: str, turn_id: str) -> dict[str, Any]:
    """Build ``turn/interrupt`` request params for an in-flight turn."""

    return {"threadId": thread_id, "turnId": turn_id}


def decide_codex_server_request(
    method: str, params: Mapping[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Decide the JSON-RPC result for a server-initiated Codex request.

    Returns ``(result_payload, accepted)``. Approval methods return ``accept``
    (or an echoed permissions grant for ``item/permissions/requestApproval``);
    every other method -- known-unsafe or unrecognized -- returns ``decline``
    (fail closed). Does NOT write to the process.
    """

    if method in _CODEX_AUTO_ACCEPT_APPROVAL_METHODS:
        if method == "item/permissions/requestApproval":
            perms = params.get("permissions")
            if not isinstance(perms, dict):
                perms = {}
            return ({"permissions": perms}, True)
        return ({"decision": "accept"}, True)
    return ({"decision": "decline"}, False)
