"""Tests for manage_openai_codex_accounts.py ``reset`` command."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_storage import (
    ManagedOAuthStorageService,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_manage_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "manage_openai_codex_accounts",
        _REPO_ROOT / "scripts" / "manage_openai_codex_accounts.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_manage = _load_manage_script()


def _make_account(
    account_id: str,
    *,
    email: str | None = None,
    rate_limited_until: int | None = None,
) -> ManagedOAuthAccount:
    return ManagedOAuthAccount(
        account_id=account_id,
        access_token=f"token_{account_id}",
        refresh_token=f"refresh_{account_id}",
        email=email,
        expiry_date=9_999_999_999_999,
        rate_limited_until=rate_limited_until,
    )


class TestAccountWithoutLocalRateLimit:
    def test_clears_timestamp_when_set(self) -> None:
        acc = _make_account("acct_x", rate_limited_until=1_700_000_000_000)
        cleared = _manage._account_without_local_rate_limit(acc)
        assert cleared.rate_limited_until is None
        assert cleared.access_token == acc.access_token
        assert cleared.refresh_token == acc.refresh_token

    def test_unchanged_when_already_clear(self) -> None:
        acc = _make_account("acct_y", rate_limited_until=None)
        cleared = _manage._account_without_local_rate_limit(acc)
        assert cleared is acc


@pytest.mark.asyncio
async def test_cmd_reset_all_clears_only_rate_limited_until(tmp_path: Path) -> None:
    storage = ManagedOAuthStorageService(tmp_path)
    a = _make_account(
        "acct_a", email="a@example.com", rate_limited_until=1_800_000_000_000
    )
    b = _make_account("acct_b", email="b@example.com", rate_limited_until=None)
    await storage.save_account(a)
    await storage.save_account(b)

    ns = SimpleNamespace(target="all")
    await _manage.cmd_reset(storage, ns)

    re_a = await storage.get_account("acct_a")
    re_b = await storage.get_account("acct_b")
    assert re_a is not None and re_b is not None
    assert re_a.rate_limited_until is None
    assert re_b.rate_limited_until is None
    assert re_a.access_token == "token_acct_a"
    assert re_a.refresh_token == "refresh_acct_a"

    raw_a = json.loads((tmp_path / "acct_a.json").read_text(encoding="utf-8"))
    assert raw_a["rate_limited_until"] is None
    assert raw_a["access_token"] == "token_acct_a"


@pytest.mark.asyncio
async def test_cmd_reset_email_case_insensitive(tmp_path: Path) -> None:
    storage = ManagedOAuthStorageService(tmp_path)
    a = _make_account(
        "acct_a",
        email="User@Example.com",
        rate_limited_until=1_800_000_000_000,
    )
    await storage.save_account(a)

    ns = SimpleNamespace(target="user@example.com")
    await _manage.cmd_reset(storage, ns)

    re_a = await storage.get_account("acct_a")
    assert re_a is not None
    assert re_a.rate_limited_until is None


@pytest.mark.asyncio
async def test_cmd_reset_email_missing_exits(tmp_path: Path) -> None:
    storage = ManagedOAuthStorageService(tmp_path)
    await storage.save_account(
        _make_account("acct_a", email="a@example.com", rate_limited_until=1)
    )

    ns = SimpleNamespace(target="nobody@example.com")
    with pytest.raises(SystemExit) as exc:
        await _manage.cmd_reset(storage, ns)
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_cmd_reset_email_ambiguous_exits(tmp_path: Path) -> None:
    storage = ManagedOAuthStorageService(tmp_path)
    await storage.save_account(
        _make_account("acct_a", email="dup@example.com", rate_limited_until=1),
    )
    await storage.save_account(
        _make_account("acct_b", email="dup@example.com", rate_limited_until=2),
    )

    ns = SimpleNamespace(target="dup@example.com")
    with pytest.raises(SystemExit) as exc:
        await _manage.cmd_reset(storage, ns)
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_cmd_reset_blank_target_exits(tmp_path: Path) -> None:
    storage = ManagedOAuthStorageService(tmp_path)
    ns = SimpleNamespace(target="   ")
    with pytest.raises(SystemExit) as exc:
        await _manage.cmd_reset(storage, ns)
    assert exc.value.code == 1


def test_reset_cli_requires_target() -> None:
    """``reset`` with no positional argument must be rejected by argparse."""
    script = _REPO_ROOT / "scripts" / "manage_openai_codex_accounts.py"
    proc = subprocess.run(
        [sys.executable, str(script), "reset"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
