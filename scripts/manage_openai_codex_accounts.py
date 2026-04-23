#!/usr/bin/env python3
"""Manage OpenAI Codex connector managed OAuth accounts.

This script handles OAuth 2.0 authorization for ChatGPT accounts used by the
openai-codex connector. Authorized accounts are stored in the configured
storage directory and can be used for managed OAuth authentication.

Authentication Flow:
    To authenticate a new account, run the 'add' subcommand:

        ./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py add

    This starts a local HTTP server, opens your browser to the ChatGPT OAuth
    consent screen, and waits for authorization to complete. After successful
    authorization, the account is automatically registered and ready for use.

    You can customize the OAuth flow with optional flags:
        --account-id NAME    Assign a custom name to the account
        --port PORT          Set a specific callback port
        --timeout SECONDS    Override the 180s timeout
        --no-browser         Print the auth URL instead of opening it

    For remote/headless environments, use --no-browser to manually open the URL.

Account Management:
    Accounts can be listed, inspected, updated (re-authorized), removed, or
    cleared of local rate-limit cooldown timestamps using the respective
    subcommands (list, show, update, remove, reset).

    Clear only persisted local rate-limit timers (does not change tokens):

        ./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py reset all
        ./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py reset user@example.com

    Clear false-positive needs_reauth / auth-failure counters (tokens unchanged):

        ./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py clear-reauth all
        ./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py clear-reauth <account_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow importing project modules when script is run directly.
sys.path.append(str(Path(__file__).parent.parent))

from src.connectors.openai_codex.managed_oauth_constants import DEFAULT_STORAGE_PATH
from src.connectors.openai_codex.managed_oauth_flow import (
    ManagedOAuthFlowError,
    ManagedOAuthFlowService,
)
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


def _format_expiry(expiry_ms: int | None) -> str:
    if expiry_ms is None:
        return "Unknown"
    dt = datetime.fromtimestamp(expiry_ms / 1000.0, tz=timezone.utc)
    return dt.isoformat()


async def cmd_list(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    summaries = await storage.list_accounts()
    if not summaries:
        print("No managed OpenAI Codex accounts found.")
        print("Use 'add' to authorize a new account.")
        return

    if args.json:
        print(json.dumps([summary.model_dump() for summary in summaries], indent=2))
        return

    header = f"{'Account ID':<24} {'Email':<36} {'Status':<14} {'Expiry (UTC)':<30}"
    print(header)
    print("-" * len(header))
    for summary in summaries:
        email = summary.email or "-"
        expiry = _format_expiry(summary.expiry_date)
        print(f"{summary.account_id:<24} {email:<36} {summary.status:<14} {expiry:<30}")


async def cmd_show(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    account = await storage.get_account(args.account_id)
    if account is None:
        print(f"Account '{args.account_id}' not found.")
        sys.exit(1)

    if args.json:
        print(account.model_dump_json(indent=2))
        return

    print(f"Account Details: {account.account_id}")
    print("-" * 42)
    print(f"Email:                {account.email or '-'}")
    print(f"ChatGPT Account ID:   {account.chatgpt_account_id or '-'}")
    print(f"Status:               {account.status}")
    print(f"Created At:           {account.created_at}")
    print(f"Updated At:           {account.updated_at}")
    print(f"Last Used:            {account.last_used or 'Never'}")
    print(f"Needs Reauth:         {account.needs_reauth}")
    print(f"Rate Limited Until:   {_format_expiry(account.rate_limited_until)}")
    print(f"Token Expiry:         {_format_expiry(account.get_effective_expiry_ms())}")
    print(f"Scope:                {account.scope}")


async def _run_authorize(
    storage: ManagedOAuthStorageService,
    *,
    account_id: str | None,
    port: int | None,
    timeout: int,
    no_browser: bool,
) -> None:
    flow = ManagedOAuthFlowService(storage)
    try:
        account = await flow.authorize(
            account_id=account_id,
            port=port,
            timeout_seconds=timeout,
            open_browser=not no_browser,
        )
    except ManagedOAuthFlowError as exc:
        print(f"Authorization failed: {exc}")
        sys.exit(1)

    print(
        f"Authorized account '{account.account_id}'"
        f"{f' ({account.email})' if account.email else ''}."
    )


async def cmd_add(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    await _run_authorize(
        storage,
        account_id=args.account_id,
        port=args.port,
        timeout=args.timeout,
        no_browser=args.no_browser,
    )


async def cmd_update(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    existing = await storage.get_account(args.account_id)
    if existing is None:
        print(f"Account '{args.account_id}' not found.")
        sys.exit(1)

    await _run_authorize(
        storage,
        account_id=args.account_id,
        port=args.port,
        timeout=args.timeout,
        no_browser=args.no_browser,
    )


async def cmd_remove(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    if not args.force:
        answer = input(f"Remove account '{args.account_id}'? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    deleted = await storage.delete_account(args.account_id)
    if not deleted:
        print(f"Account '{args.account_id}' not found.")
        sys.exit(1)
    print(f"Removed account '{args.account_id}'.")


def _account_without_local_rate_limit(
    account: ManagedOAuthAccount,
) -> ManagedOAuthAccount:
    """Return a copy with ``rate_limited_until`` cleared; other fields unchanged."""
    if account.rate_limited_until is None:
        return account
    return account.model_copy(update={"rate_limited_until": None})


async def cmd_reset(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    """Unset ``rate_limited_until`` only (OAuth tokens and other fields unchanged)."""
    target_raw = args.target.strip()
    if not target_raw:
        print(
            "Invalid usage: reset requires a target. "
            'Use "all" or an account email, e.g. reset all / reset user@example.com'
        )
        sys.exit(1)

    if target_raw.casefold() == "all":
        accounts = await storage.load_all_accounts()
        if not accounts:
            print("No managed OpenAI Codex accounts found; nothing to reset.")
            return
        cleared = 0
        for account in accounts:
            if account.rate_limited_until is None:
                continue
            updated = _account_without_local_rate_limit(account)
            await storage.save_account(updated)
            cleared += 1
            email = account.email or "-"
            print(
                f"Cleared local rate-limit cooldown for "
                f"{account.account_id} ({email})."
            )
        skipped = len(accounts) - cleared
        if cleared == 0:
            print(
                "No accounts had a local rate-limit cooldown set "
                f"({skipped} checked)."
            )
        else:
            print(f"Done. Cleared {cleared} account(s); {skipped} already clear.")
        return

    needle = target_raw.casefold()
    accounts = await storage.load_all_accounts()
    matches = [
        account for account in accounts if (account.email or "").casefold() == needle
    ]
    if not matches:
        print(f"No managed account found with email matching {target_raw!r}.")
        sys.exit(1)
    if len(matches) > 1:
        ids = ", ".join(sorted(account.account_id for account in matches))
        print(
            "Multiple accounts share that email; cannot pick one. "
            f"Matching account_id values: {ids}"
        )
        sys.exit(1)

    account = matches[0]
    updated = _account_without_local_rate_limit(account)
    if account.rate_limited_until is None:
        print(
            f"Account {account.account_id} "
            f"({account.email or '-'}) has no local rate-limit cooldown set."
        )
        return

    await storage.save_account(updated)
    print(
        f"Cleared local rate-limit cooldown for "
        f"{account.account_id} ({account.email or '-'})."
    )


def _account_cleared_reauth_flags(account: ManagedOAuthAccount) -> ManagedOAuthAccount:
    """Return a copy with ``needs_reauth`` false and auth-failure counter reset."""
    if not account.needs_reauth and account.consecutive_auth_failures == 0:
        return account
    return account.model_copy(
        update={
            "needs_reauth": False,
            "consecutive_auth_failures": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


async def cmd_clear_reauth(
    storage: ManagedOAuthStorageService,
    args: argparse.Namespace,
) -> None:
    """Clear ``needs_reauth`` and ``consecutive_auth_failures`` (OAuth tokens unchanged)."""
    target_raw = args.target.strip()
    if not target_raw:
        print(
            "Invalid usage: clear-reauth requires a target. "
            'Use "all", an account_id, or an email, e.g. clear-reauth all'
        )
        sys.exit(1)

    if target_raw.casefold() == "all":
        accounts = await storage.load_all_accounts()
        if not accounts:
            print("No managed OpenAI Codex accounts found; nothing to update.")
            return
        updated_n = 0
        for account in accounts:
            cleared = _account_cleared_reauth_flags(account)
            if cleared is account:
                continue
            await storage.save_account(cleared)
            updated_n += 1
            print(
                f"Cleared reauth flags for {cleared.account_id} "
                f"({cleared.email or '-'})."
            )
        if updated_n == 0:
            print(f"No accounts had needs_reauth or auth-failure counters set ({len(accounts)} checked).")
        else:
            print(f"Done. Updated {updated_n} account(s).")
        return

    by_id = await storage.get_account(target_raw)
    if by_id is not None:
        cleared = _account_cleared_reauth_flags(by_id)
        if cleared is by_id:
            print(
                f"Account '{by_id.account_id}' ({by_id.email or '-'}) "
                "already has needs_reauth false and zero auth-failure counter."
            )
            return
        await storage.save_account(cleared)
        print(f"Cleared reauth flags for {cleared.account_id} ({cleared.email or '-'}).")
        return

    needle = target_raw.casefold()
    accounts = await storage.load_all_accounts()
    matches = [
        account for account in accounts if (account.email or "").casefold() == needle
    ]
    if not matches:
        print(
            f"No managed account found with id {target_raw!r} or email matching "
            f"that string."
        )
        sys.exit(1)
    if len(matches) > 1:
        ids = ", ".join(sorted(account.account_id for account in matches))
        print(
            "Multiple accounts share that email; cannot pick one. "
            f"Matching account_id values: {ids}"
        )
        sys.exit(1)

    account = matches[0]
    cleared = _account_cleared_reauth_flags(account)
    if cleared is account:
        print(
            f"Account {account.account_id} ({account.email or '-'}) "
            "already has needs_reauth false and zero auth-failure counter."
        )
        return
    await storage.save_account(cleared)
    print(f"Cleared reauth flags for {cleared.account_id} ({cleared.email or '-'}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage OpenAI Codex OAuth accounts")
    parser.add_argument(
        "--storage-path",
        default=DEFAULT_STORAGE_PATH,
        help=f"Managed account directory (default: {DEFAULT_STORAGE_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List authorized accounts")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")

    show_parser = subparsers.add_parser("show", help="Show account details")
    show_parser.add_argument("account_id")
    show_parser.add_argument("--json", action="store_true", help="Output JSON")

    ADD_EPILOG = (
        "Authentication Flow:\n"
        "  This command starts a local HTTP server, opens your browser to the\n"
        "  ChatGPT OAuth consent screen, and waits for authorization to complete.\n"
        "  After successful authorization, the account is registered and ready for use.\n\n"
        "  For remote/headless environments, use --no-browser to print the auth URL."
    )
    add_parser = subparsers.add_parser(
        "add",
        help="Authorize a new account",
        epilog=ADD_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_parser.add_argument("--account-id", help="Custom local account id")
    add_parser.add_argument("--port", type=int, help="Fixed callback port")
    add_parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Authorization timeout in seconds (default: 180)",
    )
    add_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open browser automatically",
    )

    update_parser = subparsers.add_parser(
        "update",
        help="Re-authorize an existing account id",
    )
    update_parser.add_argument("account_id")
    update_parser.add_argument("--port", type=int, help="Fixed callback port")
    update_parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Authorization timeout in seconds (default: 180)",
    )
    update_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open browser automatically",
    )

    remove_parser = subparsers.add_parser("remove", help="Remove an account")
    remove_parser.add_argument("account_id")
    remove_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )

    reset_parser = subparsers.add_parser(
        "reset",
        help=(
            "Clear persisted local rate-limit cooldown (rate_limited_until only); "
            "does not modify OAuth tokens"
        ),
    )
    reset_parser.add_argument(
        "target",
        help='Use the literal word "all" for every account, or the account email',
    )

    clear_reauth_parser = subparsers.add_parser(
        "clear-reauth",
        help=(
            "Clear needs_reauth and consecutive_auth_failures on disk (tokens unchanged)"
        ),
    )
    clear_reauth_parser.add_argument(
        "target",
        help='Use "all", a storage account_id, or the account email',
    )

    args = parser.parse_args()
    storage = ManagedOAuthStorageService(args.storage_path)

    if args.command == "list":
        asyncio.run(cmd_list(storage, args))
    elif args.command == "show":
        asyncio.run(cmd_show(storage, args))
    elif args.command == "add":
        asyncio.run(cmd_add(storage, args))
    elif args.command == "update":
        asyncio.run(cmd_update(storage, args))
    elif args.command == "remove":
        asyncio.run(cmd_remove(storage, args))
    elif args.command == "reset":
        asyncio.run(cmd_reset(storage, args))
    elif args.command == "clear-reauth":
        asyncio.run(cmd_clear_reauth(storage, args))


if __name__ == "__main__":
    main()
