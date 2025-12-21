# Antigravity OAuth Backend (Internal Use Only)

This specialized backend integrates with the Antigravity app's authentication and sandbox endpoint infrastructure for internal development and compatibility testing.

## Overview

The `antigravity-oauth` backend allows the proxy to use both Gemini and Claude models via the Antigravity sandbox environment. It shares authentication credentials with the Antigravity VS Code extension.

**Supported Models**: Supports both Gemini (e.g., `gemini-2.0-flash`) and Claude (e.g., `claude-3-5-sonnet-20241022`) models.
**Authentication**: Uses Antigravity's internal OAuth tokens.

## Configuration

The backend targets the Antigravity sandbox endpoint and requires specific authentication tokens managed by the Antigravity application.

### Debugging Override Flag Required

To use this backend, you **must** launch the proxy with the following CLI flag:

```bash
--enable-antigravity-backend-debugging-override
```

Without this flag, the backend is disabled and will reject all requests with a 403 Forbidden error.

### CLI Usage

```bash
python -m src.core.cli --default-backend antigravity-oauth --enable-antigravity-backend-debugging-override
```

### Model Validation

This backend accepts any model name supported by the Antigravity sandbox, including both Gemini and Claude models.

**Valid Models**:

- `gemini-2.0-flash-exp`
- `gemini-2.5-pro`
- `claude-3-5-sonnet-20241022`
- `claude-opus-4`

The backend automatically handles the differences in API payloads and tool calling conventions between Gemini and Claude models.

## Disclaimer: Internal Development Use Only

### IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND

This backend connector is implemented **solely** for the internal development purposes of this project. Its primary function is to enable the proper discovery, analysis, and implementation of secure, protocol-specific behaviors required for interoperability and compatibility layers.

**This connector is NOT intended for general usage, production deployment, or as a means to bypass intended access restrictions.**

By using this proxy with the Antigravity OAuth backend configuration, you acknowledge and agree to the following terms, which constitute a binding arrangement between you and the authors of this project:

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Google, the Antigravity team, or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
2. **Restricted Access**: The use of the `--enable-antigravity-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's compatibility features.
3. **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this flag or backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.
5. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.
6. **Compliance with Provider Terms**: Users of any backend connectors implemented in this proxy server are strictly required to respect all related Terms of Service (ToS) and other agreements with the respective backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.
7. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of this backend or the debugging override flag.

**If you do not agree to these terms, do not use the Antigravity OAuth backend or the debugging override flag.**
