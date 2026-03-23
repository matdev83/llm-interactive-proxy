# Codex Authentication Management Guide

This guide explains how to manage ChatGPT/Codex account credentials for the OpenAI Codex connector.

## Quick Reference

### Remove Current Account
```powershell
# Windows
Remove-Item -Path "$env:USERPROFILE\.codex\auth.json" -Force
```

```bash
# Linux/Mac
rm ~/.codex/auth.json
```

### Authorize New Account

**Option 1: Using Official Codex CLI** (Recommended)
```bash
# Install Codex CLI if not already installed
# See: https://github.com/openai/codex

# Login with your ChatGPT account
codex auth login
```

**Option 2: Manual `auth.json` Creation** (Advanced)

Create `auth.json` in the appropriate location:
- **Windows**: `%USERPROFILE%\.codex\auth.json`
- **Linux/Mac**: `~/.codex/auth.json`

With this structure:
```json
{
  "tokens": {
    "access_token": "your-chatgpt-access-token-here",
    "refresh_token": "your-refresh-token-here",
    "expires_at": 1234567890
  },
  "user": {
    "email": "your-email@example.com"
  }
}
```

### Verify Current Account
```powershell
# Windows
Get-Content "$env:USERPROFILE\.codex\auth.json" | ConvertFrom-Json | Select-Object -ExpandProperty user
```

```bash
# Linux/Mac
cat ~/.codex/auth.json | jq .user
```

---

## Detailed Instructions

### Step 1: Remove Non-Functional Account

**Windows (PowerShell)**:
```powershell
# Check if auth.json exists
Test-Path "$env:USERPROFILE\.codex\auth.json"

# Remove it
Remove-Item -Path "$env:USERPROFILE\.codex\auth.json" -Force

# Verify it's gone
Test-Path "$env:USERPROFILE\.codex\auth.json"  # Should return False
```

**Linux/Mac (Bash)**:
```bash
# Check if auth.json exists
ls -la ~/.codex/auth.json

# Remove it
rm ~/.codex/auth.json

# Verify it's gone
ls -la ~/.codex/auth.json  # Should show "No such file or directory"
```

### Step 2: Authorize New Account

#### Method A: Using Official Codex CLI (Recommended)

This is the easiest and most secure method.

1. **Install Codex CLI** (if not already installed):
   ```bash
   # The official Codex CLI should be available from:
   # https://github.com/openai/codex
   
   # Or check if you have it:
   which codex  # Linux/Mac
   where codex  # Windows
   ```

2. **Login with your ChatGPT account**:
   ```bash
   codex auth login
   ```
   
   This will:
   - Open your browser
   - Ask you to log in with your ChatGPT/OpenAI account
   - Save credentials to `~/.codex/auth.json`

3. **Verify authentication**:
   ```bash
   codex auth status
   ```

#### Method B: Using Browser DevTools (Manual Extraction)

If you don't have the Codex CLI, you can manually extract your access token:

1. **Open ChatGPT in your browser** (https://chatgpt.com)

2. **Open Browser DevTools**:
   - Chrome/Edge: Press `F12` or `Ctrl+Shift+I` (Windows) / `Cmd+Option+I` (Mac)
   - Firefox: Press `F12`

3. **Get your access token**:
   - Go to the **Application** tab (Chrome/Edge) or **Storage** tab (Firefox)
   - Navigate to **Cookies** → `https://chatgpt.com`
   - Look for a cookie or session storage item containing your access token
   
   OR
   
   - Go to the **Console** tab
   - Run: `JSON.parse(localStorage.getItem('auth')).accessToken`
   - Copy the token value

4. **Create `auth.json` manually**:
   
   **Windows**:
   ```powershell
   # Create directory if it doesn't exist
   New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.codex"
   
   # Create auth.json (replace YOUR_ACCESS_TOKEN)
   @"
   {
     "tokens": {
       "access_token": "YOUR_ACCESS_TOKEN_HERE",
       "refresh_token": "",
       "expires_at": $(([DateTimeOffset]::UtcNow.AddDays(7).ToUnixTimeSeconds()))
     },
     "user": {
       "email": "your-email@example.com"
     }
   }
   "@ | Set-Content -Path "$env:USERPROFILE\.codex\auth.json"
   ```
   
   **Linux/Mac**:
   ```bash
   # Create directory if it doesn't exist
   mkdir -p ~/.codex
   
   # Create auth.json (replace YOUR_ACCESS_TOKEN)
   cat > ~/.codex/auth.json << EOF
   {
     "tokens": {
       "access_token": "YOUR_ACCESS_TOKEN_HERE",
       "refresh_token": "",
       "expires_at": $(($(date +%s) + 604800))
     },
     "user": {
       "email": "your-email@example.com"
     }
   }
   EOF
   ```

### Step 3: Verify Authentication

**Check the file exists**:
```powershell
# Windows
Test-Path "$env:USERPROFILE\.codex\auth.json"
Get-Content "$env:USERPROFILE\.codex\auth.json"
```

```bash
# Linux/Mac
ls -la ~/.codex/auth.json
cat ~/.codex/auth.json | jq .
```

**Test with the proxy**:
```bash
# Start the proxy with Codex backend
python -m src.core.cli --default-backend openai-codex:o1-mini

# In another terminal, test a request
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "o1-mini",
    "messages": [{"role": "user", "content": "Say hello in exactly 2 words"}]
  }'
```

---

## Troubleshooting

### Error: "OAuth credentials file not found"

**Solution**: Verify the file exists at the correct location:
```powershell
# Windows
Get-ChildItem "$env:USERPROFILE\.codex\auth.json"
```

```bash
# Linux/Mac
ls -la ~/.codex/auth.json
```

### Error: "401 Unauthorized" or "403 Forbidden"

**Possible causes**:
1. Access token is expired
2. Account doesn't have ChatGPT Plus/Pro subscription
3. Token was revoked

**Solution**: Re-authenticate:
```bash
# Remove old credentials
rm ~/.codex/auth.json  # Linux/Mac
# OR
Remove-Item "$env:USERPROFILE\.codex\auth.json" -Force  # Windows

# Login again
codex auth login
```

### Error: "Policy violation" (WebSocket)

This is expected! The ChatGPT backend currently restricts WebSocket messages from third-party clients. The HTTP transport will work fine.

**Solution**: Disable WebSocket for Codex (already the default):
```yaml
# config/config.yaml
backends:
  openai_codex:
    extra:
      codex:
        websocket:
          enabled: false  # Keep this as false
```

### Custom auth.json Location

If you want to use a different location for `auth.json`:

**Environment variable**:
```bash
export OPENAI_CODEX_PATH="/custom/path/to/.codex"
```

**Or in code/config**: Specify the custom path when initializing the connector.

---

## File Locations

### Default Locations

| Platform | Path |
|----------|------|
| Windows | `%USERPROFILE%\.codex\auth.json` |
| Linux | `~/.codex/auth.json` |
| macOS | `~/.codex/auth.json` |

### Expanded Paths (Examples)

| Platform | Example |
|----------|---------|
| Windows | `C:\Users\YourName\.codex\auth.json` |
| Linux | `/home/yourname/.codex/auth.json` |
| macOS | `/Users/yourname/.codex/auth.json` |

---

## Security Notes

1. **Keep `auth.json` secure**: This file contains your ChatGPT access token
2. **Don't commit to Git**: Add `.codex/` to your `.gitignore`
3. **Token rotation**: Tokens expire; you'll need to re-authenticate periodically
4. **Refresh tokens**: The proxy can automatically refresh expired tokens if a valid refresh_token is present

---

## Quick Commands Summary

```powershell
# Windows PowerShell

# 1. Remove old account
Remove-Item "$env:USERPROFILE\.codex\auth.json" -Force

# 2. Verify it's removed
Test-Path "$env:USERPROFILE\.codex\auth.json"

# 3. Login with Codex CLI (if available)
codex auth login

# 4. Or create auth.json manually (see detailed instructions above)

# 5. Verify new account
Get-Content "$env:USERPROFILE\.codex\auth.json" | ConvertFrom-Json | Select user

# 6. Test with proxy
python -m src.core.cli
```

```bash
# Linux/Mac Bash

# 1. Remove old account
rm ~/.codex/auth.json

# 2. Verify it's removed
ls ~/.codex/auth.json  # Should error

# 3. Login with Codex CLI (if available)
codex auth login

# 4. Or create auth.json manually (see detailed instructions above)

# 5. Verify new account
cat ~/.codex/auth.json | jq .user

# 6. Test with proxy
python -m src.core.cli
```

---

## Need Help?

- Check proxy logs: `var/logs/proxy-debug-*.log`
- Check auth.json format: It should be valid JSON
- Verify ChatGPT subscription: You need ChatGPT Plus/Pro
- Use HTTP (not WebSocket) for now due to backend restrictions
