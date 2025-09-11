# Google Cloud Project ID Authentication for Gemini API

## Overview

This document describes how to implement a Gemini API backend that uses Google Cloud Project ID-based authentication. This is one of three distinct authentication methods for Gemini:

1. **Personal OAuth** (free-tier, managed project) - Covered in `gemini_oauth_personal.py`
2. **API Key** (metered/paid) - Standard Gemini API with key
3. **Cloud Project ID** (this document) - Uses your own GCP project with OAuth

The Cloud Project ID method allows you to use your own Google Cloud Project with proper IAM permissions and billing, giving you more control over usage, quotas, and costs.

## Key Differences from Other Methods

### vs Personal OAuth (free-tier)

- **Project Ownership**: Uses YOUR Google Cloud project, not a Google-managed one
- **Billing**: Charges to your GCP billing account
- **Quotas**: Uses your project's quotas and limits
- **Onboarding**: Must specify `cloudaicompanionProject` in ALL requests
- **Tier**: Uses `standard-tier`, not `free-tier`

### vs API Key

- **Authentication**: Uses OAuth2 tokens, not API keys
- **Endpoint**: Uses `cloudcode-pa.googleapis.com`, not `generativelanguage.googleapis.com`
- **Features**: Access to Code Assist features and models
- **Security**: More secure with OAuth2 flow

## Prerequisites

1. **Google Cloud Project**
   - Create a GCP project or use an existing one
   - Enable billing on the project
   - Note your Project ID (e.g., `my-project-123`)

2. **Required APIs**
   Enable these APIs in your GCP project:

   ```
   - Cloud AI Companion API
   - Cloud Resource Manager API
   - Identity and Access Management (IAM) API
   ```

3. **OAuth Credentials**
   - Still uses the same OAuth client credentials as the CLI
   - But tokens are scoped to YOUR project

## Implementation Guide

### 1. Backend Class Structure

```python
class GeminiCloudProjectConnector(GeminiBackend):
    """
    Gemini connector using Google Cloud Project ID authentication.
    
    This connector uses OAuth2 authentication with a user-specified
    Google Cloud Project, allowing for standard-tier features with
    proper billing and quotas.
    """
    
    backend_type: str = "gemini-cloud-project"
    
    def __init__(self, client: httpx.AsyncClient, **kwargs: Any) -> None:
        super().__init__(client)
        self.name = "gemini-cloud-project"
        self.project_id = kwargs.get("gcp_project_id")  # Required parameter
        self.credentials_path = kwargs.get("credentials_path")
        self._oauth_credentials = None
```

### 2. Project Discovery and Validation

The key difference is in the `_discover_project_id` method:

```python
async def _discover_project_id(self, auth_session) -> str:
    """
    Validate and use the user-specified GCP project ID.
    
    Unlike free-tier which discovers a managed project,
    this uses the user's actual GCP project.
    """
    if not self.project_id:
        raise ValueError("GCP Project ID is required for cloud-project authentication")
    
    # Prepare metadata WITH the project ID
    client_metadata = {
        "ideType": "IDE_UNSPECIFIED",
        "platform": "PLATFORM_UNSPECIFIED", 
        "pluginType": "GEMINI",
        "duetProject": self.project_id,  # User's project
    }
    
    # Call loadCodeAssist to validate the project
    load_request = {
        "cloudaicompanionProject": self.project_id,  # User's project
        "metadata": client_metadata,
    }
    
    url = f"{self.gemini_api_base_url}/v1internal:loadCodeAssist"
    load_response = await asyncio.to_thread(
        auth_session.request,
        method="POST",
        url=url,
        json=load_request,
        headers={"Content-Type": "application/json"},
        timeout=30.0,
    )
    
    if load_response.status_code != 200:
        raise BackendError(f"Project validation failed: {load_response.text}")
    
    load_data = load_response.json()
    
    # Check if project is already set up
    if load_data.get("cloudaicompanionProject"):
        return load_data["cloudaicompanionProject"]
    
    # Need to onboard the project
    return await self._onboard_project(auth_session, load_data)
```

### 3. Project Onboarding (Critical Difference)

```python
async def _onboard_project(self, auth_session, load_data) -> str:
    """
    Onboard the user's GCP project for Code Assist.
    
    CRITICAL: For standard-tier with user project, we MUST include
    the cloudaicompanionProject field in the request.
    """
    # Find the standard-tier (NOT free-tier)
    allowed_tiers = load_data.get("allowedTiers", [])
    standard_tier = None
    
    for tier in allowed_tiers:
        if tier.get("id") == "standard-tier":
            standard_tier = tier
            break
    
    if not standard_tier:
        raise BackendError("Standard tier not available for this project")
    
    # Verify this tier supports user-defined projects
    if not standard_tier.get("userDefinedCloudaicompanionProject"):
        raise BackendError(
            "Standard tier does not support user-defined projects. "
            "This might be a configuration issue."
        )
    
    # CRITICAL: Include cloudaicompanionProject for standard-tier!
    # This is the opposite of free-tier which must NOT include it
    onboard_request = {
        "tierId": "standard-tier",
        "cloudaicompanionProject": self.project_id,  # MUST include for standard
        "metadata": {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
            "duetProject": self.project_id,  # Also include in metadata
        },
    }
    
    # Call onboardUser
    onboard_url = f"{self.gemini_api_base_url}/v1internal:onboardUser"
    lro_response = await asyncio.to_thread(
        auth_session.request,
        method="POST",
        url=onboard_url,
        json=onboard_request,
        headers={"Content-Type": "application/json"},
        timeout=30.0,
    )
    
    if lro_response.status_code != 200:
        error_detail = lro_response.text
        if "Permission denied" in error_detail:
            raise BackendError(
                f"Permission denied for project {self.project_id}. "
                "Ensure the Cloud AI Companion API is enabled and "
                "you have the necessary IAM permissions."
            )
        raise BackendError(f"Onboarding failed: {error_detail}")
    
    # Poll for completion (same as free-tier)
    lro_data = await self._poll_operation(auth_session, onboard_url, onboard_request)
    
    # Extract the project ID (should be the same as input)
    response_data = lro_data.get("response", {})
    cloudai_project = response_data.get("cloudaicompanionProject", {})
    confirmed_project_id = cloudai_project.get("id", self.project_id)
    
    if confirmed_project_id != self.project_id:
        logger.warning(
            f"Project ID mismatch: expected {self.project_id}, "
            f"got {confirmed_project_id}"
        )
    
    return confirmed_project_id
```

### 4. Authentication Flow

The OAuth flow remains similar but with project-specific scopes:

```python
async def _refresh_token_if_needed(self) -> bool:
    """
    Refresh OAuth token with project-specific context.
    """
    # Create credentials with project-specific configuration
    credentials = google.oauth2.credentials.Credentials(
        token=self._oauth_credentials.get("access_token"),
        refresh_token=self._oauth_credentials.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GEMINI_CLI_CLIENT_ID,
        client_secret=GEMINI_CLI_CLIENT_SECRET,
        scopes=GEMINI_CLI_OAUTH_SCOPES,
        # Could add project-specific parameters here if needed
    )
    
    # Refresh the token
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    
    # Update stored credentials
    self._oauth_credentials.update({
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "expiry_date": int(credentials.expiry.timestamp() * 1000),
    })
    
    return True
```

### 5. API Calls with Project Context

```python
async def _chat_completions_code_assist(
    self, 
    request_data: Any,
    processed_messages: list[Any],
    effective_model: str,
    **kwargs: Any,
) -> Any:
    """
    Make API calls using the user's GCP project.
    """
    # Ensure we have a valid project ID
    if not self.project_id:
        raise ValueError("Project ID not set")
    
    # Convert messages to Gemini format
    contents = self._convert_messages_to_gemini_format(processed_messages)
    
    # Prepare request with USER'S project ID
    request_body = {
        "model": effective_model,
        "project": self.project_id,  # User's GCP project
        "request": {
            "contents": contents,
            "generationConfig": {
                "temperature": float(getattr(request_data, "temperature", 0.7)),
                "maxOutputTokens": int(getattr(request_data, "max_tokens", 1024)),
                "topP": float(getattr(request_data, "top_p", 0.95)),
            },
        },
    }
    
    # Make the API call (same endpoint as free-tier)
    url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
    response = await self._make_authenticated_request(
        auth_session, 
        url, 
        request_body
    )
    
    return self._process_sse_response(response)
```

## Configuration

### Required Parameters

```python
backend_config = {
    "backend_type": "gemini-cloud-project",
    "gcp_project_id": "my-project-123",  # REQUIRED
    "credentials_path": "~/.gemini/oauth_creds.json",  # Optional, defaults to ~/.gemini
    "gemini_api_base_url": "https://cloudcode-pa.googleapis.com",  # Default
}
```

### Environment Variables

```bash
# Required
export GCP_PROJECT_ID="my-project-123"

# Optional
export GEMINI_CREDENTIALS_PATH="~/.gemini/oauth_creds.json"
```

## Error Handling

### Common Errors and Solutions

1. **403 Permission Denied**

   ```
   Error: Permission denied on resource project my-project-123
   ```

   **Solution**:
   - Enable Cloud AI Companion API in GCP Console
   - Ensure user has `roles/cloudaicompanion.user` IAM role
   - Verify billing is enabled

2. **400 Precondition Failed**

   ```
   Error: Precondition check failed
   ```

   **Solution**:
   - Ensure you're including `cloudaicompanionProject` in requests
   - Verify using `standard-tier`, not `free-tier`

3. **Project Not Found**

   ```
   Error: Project my-project-123 not found
   ```

   **Solution**:
   - Verify project ID is correct (not project name)
   - Ensure project exists and is active
   - Check you have access to the project

## Testing

### Test Script

```python
import asyncio
from pathlib import Path
import httpx

async def test_cloud_project_auth():
    """Test Gemini with Cloud Project ID authentication."""
    
    # Initialize the connector
    client = httpx.AsyncClient()
    connector = GeminiCloudProjectConnector(
        client=client,
        gcp_project_id="my-project-123",  # Your project ID
        credentials_path=Path.home() / ".gemini" / "oauth_creds.json"
    )
    
    # Initialize
    await connector.initialize()
    
    # Test API call
    messages = [
        {"role": "user", "content": "Hello, what's 2+2?"}
    ]
    
    response = await connector.chat_completions(
        request_data={"temperature": 0.7, "max_tokens": 100},
        processed_messages=messages,
        effective_model="gemini-1.5-flash-002"
    )
    
    print(f"Response: {response.content}")
    
    # Cleanup
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(test_cloud_project_auth())
```

## Billing and Quotas

### Understanding Costs

When using Cloud Project ID authentication:

1. **Billing**: All API usage is billed to your GCP project
2. **Quotas**: Subject to your project's quotas and limits
3. **Monitoring**: Can track usage in GCP Console under "APIs & Services"

### Setting Up Budget Alerts

```bash
# Create a budget alert for your project
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="Gemini API Budget" \
  --budget-amount=100 \
  --threshold-rule=percent=90
```

## Security Best Practices

1. **Never commit credentials**
   - Keep `oauth_creds.json` in `.gitignore`
   - Use environment variables for project IDs

2. **Use Service Accounts for Production**

   ```python
   # For production, consider using service account credentials
   from google.oauth2 import service_account
   
   credentials = service_account.Credentials.from_service_account_file(
       'path/to/service-account-key.json',
       scopes=GEMINI_CLI_OAUTH_SCOPES
   )
   ```

3. **Implement Rate Limiting**
   - Add rate limiting to prevent unexpected charges
   - Monitor usage regularly

4. **Restrict IAM Permissions**
   - Grant minimal necessary permissions
   - Use `roles/cloudaicompanion.user`, not `roles/owner`

## Comparison Table

| Feature | Free-tier (Personal OAuth) | Cloud Project ID | API Key |
|---------|---------------------------|------------------|---------|
| **Project** | Google-managed | User's GCP project | N/A |
| **Billing** | Free (with limits) | Pay-as-you-go | Metered |
| **Tier** | free-tier | standard-tier | N/A |
| **Onboarding Field** | NO cloudaicompanionProject | MUST include cloudaicompanionProject | N/A |
| **Endpoint** | cloudcode-pa.googleapis.com | cloudcode-pa.googleapis.com | generativelanguage.googleapis.com |
| **Auth Method** | OAuth2 | OAuth2 | API Key |
| **Setup Complexity** | Low (just credentials) | Medium (GCP project setup) | Low (just API key) |
| **Production Ready** | No | Yes | Yes |
| **Custom Quotas** | No | Yes | Limited |

## Troubleshooting Checklist

- [ ] GCP Project ID is correct (not project name)
- [ ] Cloud AI Companion API is enabled
- [ ] Billing is enabled on the project
- [ ] User has necessary IAM permissions
- [ ] OAuth credentials are valid and not expired
- [ ] Using `standard-tier` in onboarding request
- [ ] Including `cloudaicompanionProject` in ALL requests
- [ ] Using correct endpoint (cloudcode-pa.googleapis.com)
- [ ] Using valid model names (gemini-1.5-flash-002, etc.)

## References

- [Google Cloud AI Companion API Documentation](https://cloud.google.com/ai-companion/docs)
- [OAuth 2.0 for Google APIs](https://developers.google.com/identity/protocols/oauth2)
- [Gemini CLI Source Code](https://github.com/google/gemini-cli)
- [GCP IAM Roles](https://cloud.google.com/iam/docs/understanding-roles)
