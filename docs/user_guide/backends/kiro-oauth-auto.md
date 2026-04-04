# Kiro OAuth Auto Backend

The `kiro-oauth-auto` backend provides a self-managed OAuth flow for Amazon Kiro / Amazon Q Developer streaming APIs, using stored credentials (similar to `gemini-oauth-auto`).

## 1) Authenticate (Builder ID device code)

The account tool lives in the **`llm-proxy-oauth-connectors`** package (adjust the path to your clone). Example:

```powershell
./.venv/Scripts/python.exe C:/path/to/llm-proxy-oauth-connectors/scripts/manage_kiro_accounts.py --storage-path var/kiro_oauth_accounts add
```

Place `--storage-path` **before** the subcommand (`add`, `list`, …); it is a global option on the main parser.

This prints a verification URL and user code. Complete the login in your browser; the script then stores credentials under `var/kiro_oauth_accounts/`.

To list stored accounts:

```powershell
./.venv/Scripts/python.exe .../manage_kiro_accounts.py --storage-path var/kiro_oauth_accounts list
```

**Cooldowns and operator actions**

- List `rate_limited_until`, quota-failure streak, and `last_success_at` for every account:

```powershell
./.venv/Scripts/python.exe .../manage_kiro_accounts.py --storage-path var/kiro_oauth_accounts cooldowns
```

- Clear a stuck cooldown (after you know quota has reset); add `--reset-failures` to zero the streak:

```powershell
./.venv/Scripts/python.exe .../manage_kiro_accounts.py --storage-path var/kiro_oauth_accounts clear-cooldown MY_ACCOUNT_ID --force
```

## 2) Configure the backend

Add to `config/config.yaml`:

```yaml
backends:
  kiro-oauth-auto:
    type: kiro-oauth-auto
    extra:
      storage_path: var/kiro_oauth_accounts
      selection_strategy: first-available   # or round-robin
      refresh_buffer_seconds: 300
      preferred_endpoint: codewhisperer     # or amazonq
      origin: AI_EDITOR                     # or CLI
      # Quota / rate-limit backoff (402 MONTHLY_REQUEST_COUNT, 429, etc.)
      monthly_quota_backoff_mode: next_calendar_month_utc  # or fixed_seconds
      monthly_quota_backoff_fixed_seconds: 604800         # 7d; used for fixed_seconds and non-monthly 402 quota
      monthly_quota_backoff_min_seconds: 86400            # floor when using next_calendar_month_utc
      monthly_quota_backoff_max_seconds: null             # optional cap (seconds) on monthly backoff; null = no cap
      account_reload_interval_seconds: 60                 # reload account JSON from disk periodically; 0 = off
      transient_rate_limit_default_seconds: 30             # 429 without Retry-After
      transient_rate_limit_max_seconds: 3600              # cap Retry-After; omit or set null in YAML for no cap
```

When an account hits **monthly** quota (`MONTHLY_REQUEST_COUNT`), the connector backs off until **the next calendar month (UTC)** by default (with at least `monthly_quota_backoff_min_seconds`), optionally capped by `monthly_quota_backoff_max_seconds`. Other accounts in `storage_path` are preferred while the first is in cooldown. Among eligible accounts, the connector prefers **lower `consecutive_quota_failures`**, then **more recent `last_success_at`**, then never-used / older `last_used`, then stable `account_id` order. New account files are picked up without a full proxy restart when `account_reload_interval_seconds` is greater than zero.

**Desktop notification (monthly quota only):** When desktop notifications are **effectively enabled** (see [Access modes: defaults and precedence](../access-modes.md#desktop-notifications-defaults-and-precedence); typically **on** for default Single User Mode on `127.0.0.1`), the connector shows one OS notification the first time a given account enters **monthly** quota cooldown for a given cooldown window. Transient **429** / short backoffs do **not** trigger this. The same window does not spam repeated toasts; after a successful completion on that account, a later monthly hit can notify again.

## 3) Enable the backend (debugging override)

The Kiro OAuth Auto backend is restricted and requires an explicit debugging override flag to enable:

```powershell
./.venv/Scripts/python.exe -m src.core.cli --enable-kiro-oauth-auto-backend-debugging-override
```

This flag is required because the backend is reserved for internal development and debugging purposes.

## 4) Run with this backend

```powershell
./.venv/Scripts/python.exe -m src.core.cli --default-backend kiro-oauth-auto --enable-kiro-oauth-auto-backend-debugging-override
```

## Model names

The backend reports models with the `amazon/` vendor prefix. Example:

- `amazon/claude-sonnet-4.5`
