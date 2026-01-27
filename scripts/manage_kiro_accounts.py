#!/usr/bin/env python3
"""
Management script for Kiro OAuth Auto-Connector accounts.

Provides commands to list, add, update, show, and remove AWS/Kiro accounts
used for Kiro inference streaming APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Add src to sys.path to allow imports from the project
sys.path.append(str(Path(__file__).parent.parent))

from src.connectors.kiro_oauth_auto.constants import (
    DEFAULT_STORAGE_PATH,
    SOCIAL_START_URL,
)
from src.connectors.kiro_oauth_auto.errors import OAuthError
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.oauth_flow import OAuthFlowService
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService


async def cmd_list(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """List all registered accounts."""
    summaries = await storage.list_accounts()

    if not summaries:
        print("No accounts registered.")
        print("Use 'add' command to register a new account.")
        return

    if args.json:
        print(json.dumps([s.model_dump() for s in summaries], indent=2))
        return

    # Print table header
    header = f"{'Account ID':<25} {'Method':<15} {'Region':<12} {'Status':<10} {'Last Used':<25}"
    print(header)
    print("-" * len(header))

    for s in summaries:
        last_used = s.last_used or "Never"
        print(
            f"{s.account_id:<25} {s.auth_method:<15} {s.region:<12} {s.status:<10} {last_used:<25}"
        )


async def cmd_add(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Add a new Kiro/AWS account via Builder ID or Social device flow."""
    auth_method = args.method
    # If method is social, we use the specific social signin URL.
    # Otherwise we use the provided start_url (default view.awsapps.com/start)
    start_url = SOCIAL_START_URL if auth_method == "social" else args.start_url
    account_id = args.account_id or f"{auth_method}-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=30.0)) as client:
        flow = OAuthFlowService(http_client=client)
        try:
            # For Builder ID, we must register/start with the specific start_url.
            # For social/other flows, sometimes the service is sensitive to the URL format.
            reg_url = start_url

            client_id, client_secret = await flow.register_oidc_client(
                region=args.region, start_url=reg_url
            )
            device = await flow.start_device_authorization(
                client_id=client_id,
                client_secret=client_secret,
                region=args.region,
                start_url=reg_url,
            )

            url = device.verification_uri_complete or device.verification_uri
            print(f"\nMethod: {auth_method}")
            print("Open this URL to authorize:")
            print(f"  {url}")
            print(f"\nUser code: {device.user_code}")
            print(
                f"Expires in: {device.expires_in_seconds}s, poll interval: {device.interval_seconds}s"
            )
            print("\nWaiting for authorization…")

            access_token, refresh_token, expires_in = await flow.poll_for_token(
                client_id=client_id,
                client_secret=client_secret,
                device_code=device.device_code,
                region=args.region,
                poll_interval_seconds=device.interval_seconds,
                timeout_seconds=device.expires_in_seconds,
            )

            expiry_date_ms = int((time.time() + expires_in) * 1000)
            account = StoredAccount(
                account_id=account_id,
                auth_method=auth_method,  # type: ignore
                region=args.region,
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
                expiry_date=expiry_date_ms,
            )
            await storage.save_account(account)

            expires_at = datetime.fromtimestamp(
                account.expiry_date / 1000, tz=timezone.utc
            ).isoformat()
            print(
                f"\nSuccessfully added account: {account.account_id} (expires at {expires_at})"
            )

        except OAuthError as e:
            print(f"\nError: {e}")
            sys.exit(1)


async def cmd_update(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Update (re-authorize) an existing account."""
    account = await storage.get_account(args.account_id)
    if not account:
        print(f"Error: Account '{args.account_id}' not found.")
        sys.exit(1)

    # Re-use the add logic with fixed account_id and method
    args.region = account.region
    args.method = account.auth_method
    args.start_url = "https://view.awsapps.com/start"  # Default if not social
    await cmd_add(storage, args)


async def cmd_remove(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Remove a registered account."""
    if not args.force:
        confirm = input(
            f"Are you sure you want to remove account '{args.account_id}'? [y/N] "
        )
        if confirm.lower() != "y":
            print("Aborted.")
            return

    deleted = await storage.delete_account(args.account_id)
    if deleted:
        print(f"Removed account: {args.account_id}")
    else:
        print(f"Error: Account '{args.account_id}' not found.")
        sys.exit(1)


async def cmd_show(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Show detailed account information."""
    account = await storage.get_account(args.account_id)
    if not account:
        print(f"Error: Account '{args.account_id}' not found.")
        sys.exit(1)

    if args.json:
        print(account.model_dump_json(indent=2))
        return

    print(f"Account Details: {account.account_id}")
    print("-" * 40)
    print(f"Auth Method:   {account.auth_method}")
    print(f"Region:        {account.region}")
    print(f"Created At:    {account.created_at}")
    print(f"Updated At:    {account.updated_at}")
    print(f"Last Used:     {account.last_used or 'Never'}")
    expiry_dt = datetime.fromtimestamp(account.expiry_date / 1000, tz=timezone.utc)
    print(f"Expiry Date:   {account.expiry_date} ({expiry_dt.isoformat()})")
    print(f"Status:        {'expired' if account.is_expired() else 'valid'}")


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Manage Kiro OAuth accounts")
    parser.add_argument(
        "--storage-path",
        default=DEFAULT_STORAGE_PATH,
        help=f"Path to storage directory (default: {DEFAULT_STORAGE_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.required = True

    # List command
    list_parser = subparsers.add_parser("list", help="List registered accounts")
    list_parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new Kiro/AWS account")
    add_parser.add_argument("--account-id", help="Custom identifier for this account")
    add_parser.add_argument(
        "--region", default="us-east-1", help="OIDC region (default: us-east-1)"
    )
    add_parser.add_argument(
        "--method",
        choices=["builderid", "social"],
        default="builderid",
        help="Authentication method (default: builderid)",
    )
    add_parser.add_argument(
        "--start-url",
        default="https://view.awsapps.com/start",
        help="Custom OIDC start URL",
    )

    # Update command
    update_parser = subparsers.add_parser(
        "update", help="Update (re-authorize) an existing account"
    )
    update_parser.add_argument("account_id", help="Identifier of the account to update")

    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Remove a registered account")
    remove_parser.add_argument("account_id", help="Identifier of the account to remove")
    remove_parser.add_argument(
        "--force", action="store_true", help="Skip confirmation prompt"
    )

    # Show command
    show_parser = subparsers.add_parser(
        "show", help="Show detailed account information"
    )
    show_parser.add_argument("account_id", help="Identifier of the account to show")
    show_parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    # Compatibility alias: builderid-login
    login_parser = subparsers.add_parser("builderid-login", help="Alias for 'add'")
    login_parser.add_argument("--account-id", help="Custom identifier for this account")
    login_parser.add_argument(
        "--region", default="us-east-1", help="OIDC region (default: us-east-1)"
    )
    login_parser.add_argument("--method", default="builderid", help=argparse.SUPPRESS)
    login_parser.add_argument(
        "--start-url", default="https://view.awsapps.com/start", help=argparse.SUPPRESS
    )

    args = parser.parse_args()
    storage = TokenStorageService(storage_path=args.storage_path)

    if args.command == "list":
        await cmd_list(storage, args)
    elif args.command in ("add", "builderid-login"):
        await cmd_add(storage, args)
    elif args.command == "update":
        await cmd_update(storage, args)
    elif args.command == "remove":
        await cmd_remove(storage, args)
    elif args.command == "show":
        await cmd_show(storage, args)

    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(_amain()))
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
