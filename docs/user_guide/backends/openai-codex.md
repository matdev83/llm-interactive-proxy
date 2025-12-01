# OpenAI Codex Backend

The OpenAI Codex backend connector is a specialized integration designed to route requests through the OpenAI Codex / Responses API infrastructure using OAuth tokens. It mimics the authentication and request patterns of the Codex CLI to facilitate development and compatibility testing.

## Configuration

To use the OpenAI Codex backend, you can configure it via environment variables or the `config.yaml` file.

### Basic Configuration

**YAML:**
```yaml
backends:
  openai_codex:
    type: openai-codex
```

**Environment Variables:**
- `OPENAI_CODEX_PATH`: Path to the Codex configuration directory containing `auth.json` (optional).
- `OPENAI_API_BASE_URL`: Override for the API base URL.

### Authentication

The connector attempts to automatically locate Codex authentication tokens from standard locations:
- Windows: `%USERPROFILE%\.codex\auth.json`
- Cross-platform: `~/.codex/auth.json`

## Debugging Override

The backend is disabled by default to prevent accidental usage.

To enable this backend for debugging purposes, you must use the CLI flag:
```bash
--enable-openai-codex-backend-debugging-override
```

---

## Disclaimer: Internal Development Use Only

**IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND**

This backend connector is implemented **solely** for the internal development purposes of this project. Its primary function is to enable the proper discovery, analysis, and implementation of secure, protocol-specific behaviors required for interoperability and compatibility layers.

**This connector is NOT intended for general usage, production deployment, or as a means to bypass intended access restrictions.**

By using this proxy with the OpenAI Codex backend configuration, you acknowledge and agree to the following terms, which constitute a binding arrangement between you and the authors of this project:

1.  **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** OpenAI, Microsoft, or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
2.  **Restricted Access**: The use of the `--enable-openai-codex-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's compatibility features.
3.  **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4.  **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this flag or backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.
5.  **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.
6.  **Compliance with Provider Terms**: Users of any backend connectors implemented in this proxy server are strictly required to respect all related Terms of Service (ToS) and other agreements with the respective backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.
7.  **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of this backend or the debugging override flag.

**If you do not agree to these terms, do not use the OpenAI Codex backend or the debugging override flag.**
