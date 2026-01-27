# Kiro OAuth Auto Backend

The `kiro-oauth-auto` backend provides a self-managed OAuth flow for Amazon Kiro / Amazon Q Developer streaming APIs, using stored credentials (similar to `gemini-oauth-auto`).

## 1) Authenticate (Builder ID device code)

Run:

```powershell
./.venv/Scripts/python.exe scripts/manage_kiro_accounts.py add
```

This prints a verification URL and user code. Complete the login in your browser; the script then stores credentials under `var/kiro_oauth_accounts/`.

To list stored accounts:

```powershell
./.venv/Scripts/python.exe scripts/manage_kiro_accounts.py list
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
```

## 3) Run with this backend

```powershell
./.venv/Scripts/python.exe -m src.core.cli --default-backend kiro-oauth-auto
```

## Model names

The backend reports models with the `amazon/` vendor prefix. Example:

- `amazon/claude-sonnet-4.5`

