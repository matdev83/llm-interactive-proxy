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

**Debugging Override Flag Required:**

To use this backend, you **must** launch the proxy with the following CLI flag:

```bash
--enable-gemini-oauth-auto-backend-debugging-override
```

Without this flag, the backend is disabled and will reject all requests with a 403 Forbidden error.

```bash
python -m src.core.cli --default-backend gemini-oauth-auto --enable-gemini-oauth-auto-backend-debugging-override
```

## Disclaimer: Internal Development Use Only

**IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND**

This backend connector is implemented **solely** for the internal development purposes of this project. Its primary function is to enable the proper discovery, analysis, and implementation of secure, protocol-specific behaviors required for interoperability and compatibility layers.

**This connector is NOT intended for general usage, production deployment, or as a means to bypass intended access restrictions.**

By using this proxy with the Gemini OAuth Auto backend configuration, you acknowledge and agree to the following terms, which constitute a binding arrangement between you and the authors of this project:

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Google or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
2. **Restricted Access**: The use of the `--enable-gemini-oauth-auto-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's compatibility features.
3. **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this flag or backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.
5. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.
6. **Compliance with Provider Terms**: Users of any backend connectors implemented in this proxy server are strictly required to respect all related Terms of Service (ToS) and other agreements with the respective backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.
7. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of this backend or the debugging override flag.

**If you do not agree to these terms, do not use the Gemini OAuth Auto backend or the debugging override flag.**

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
