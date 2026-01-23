# Gemini OAuth Auto Backend

The `gemini-oauth-auto` backend provides a multi-account, self-managed OAuth solution for Google Gemini models. It allows you to register multiple Google accounts and automatically rotates between them, providing high availability and effectively bypassing single-account rate limits.

## Features

- **Multi-Account Management**: Store and use multiple Google accounts simultaneously.
- **Automatic Rotation**: Seamlessly switches to the next available account when a "Quota Exceeded" (429) error is detected.
- **Self-Contained OAuth**: Handles the entire browser-based authorization flow without requiring external CLI tools like `gcloud` or `gemini`.
- **Proactive Token Refresh**: Automatically refreshes access tokens in the background before they expire.
- **Round-Robin Selection**: Distributes requests across all healthy accounts to maximize total throughput.

## Setup and Configuration

### 1. Management Script

The `scripts/manage_gemini_accounts.py` script is the primary tool for managing your accounts.

#### Add an Account
To register a new account, run:
```bash
python scripts/manage_gemini_accounts.py add
```
This will:
1. Start a local temporary web server.
2. Open your default web browser to Google's authorization page.
3. After you grant permission, receive the authorization code and exchange it for tokens.
4. Securely store the tokens in `var/gemini_oauth_accounts/`.

#### List Accounts
To see all registered accounts and their current status:
```bash
python scripts/manage_gemini_accounts.py list
```

#### Remove an Account
```bash
python scripts/manage_gemini_accounts.py remove <account-id>
```

### 2. Proxy Configuration

Enable the backend in your `config.yaml`:

```yaml
backends:
  gemini-oauth-auto:
    type: gemini-oauth-auto
    extra:
      selection_strategy: "round-robin"  # Options: round-robin, random, first-available
      refresh_buffer_seconds: 300       # Refresh tokens 5 minutes before expiry
```

### 3. Launching the Proxy

Launch the proxy with the `gemini-oauth-auto` backend:

```bash
python -m src.core.cli --default-backend gemini-oauth-auto
```

## How It Works

### Account Rotation
When a request fails with a `429 Quota Exceeded` error, the connector:
1. Marks the current account as "exhausted" for a cooldown period.
2. Immediately selects the next available account from the pool.
3. Transparently handles subsequent requests using the new account.

### Health Monitoring
The backend's health status (visible via `/health` or CLI) reflects:
- Whether any accounts are registered.
- How many accounts are currently valid and not in cooldown.
- Endpoint connectivity to Google's API.

## Storage and Security

- **Persistence**: Accounts are stored as individual JSON files in `var/gemini_oauth_accounts/`.
- **Permissions**: On POSIX systems, files are created with `0600` permissions (readable/writable only by the owner).
- **Secrets**: Refresh tokens are stored locally to allow for automatic background refreshing. Ensure the `var/` directory is protected.

## Troubleshooting

### "No valid OAuth accounts available"
This error occurs if no accounts have been added yet or all tokens have become invalid. Use `python scripts/manage_gemini_accounts.py add` to register an account.

### Browser doesn't open
If `webbrowser.open` fails, the script will print the authorization URL. Copy and paste this URL into your browser manually.

### Port Conflicts
By default, the authorization server uses a random available port. If you need a fixed port, use:
```bash
python scripts/manage_gemini_accounts.py add --port 8080
```
