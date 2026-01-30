"""Constants for the Kiro OAuth Auto connector."""

ACCOUNT_ID_MAX_LENGTH = 64
ACCOUNT_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"

DEFAULT_STORAGE_PATH = "var/kiro_oauth_accounts"
DEFAULT_RATE_LIMIT_SECONDS = 10.0

DEFAULT_REGION = "us-east-1"
DEFAULT_START_URL = "https://view.awsapps.com/start"
SOCIAL_START_URL = "https://signin.aws/social"

# Scopes observed in Kiro flows (Builder ID / IdC style)
DEFAULT_OIDC_SCOPES: tuple[str, ...] = (
    "codewhisperer:completions",
    "codewhisperer:analysis",
    "codewhisperer:conversations",
    "codewhisperer:transformations",
    "codewhisperer:taskassist",
)

# Kiro inference endpoints (observed)
CODEWHISPERER_GENERATE_URL = (
    "https://codewhisperer.us-east-1.amazonaws.com/generateAssistantResponse"
)
AMAZONQ_GENERATE_URL = "https://q.us-east-1.amazonaws.com/generateAssistantResponse"

CODEWHISPERER_LIST_MODELS_URL = (
    "https://codewhisperer.us-east-1.amazonaws.com/"
    "ListAvailableModels?origin=AI_EDITOR&maxResults=50"
)

# Request headers (observed User-Agent values)
KIRO_USER_AGENT = (
    "aws-sdk-js/1.0.18 ua/2.1 os/windows lang/js md/nodejs#20.16.0 "
    "api/codewhispererstreaming#1.0.18 m/E KiroIDE-0.6.18"
)
KIRO_AMZ_USER_AGENT = "aws-sdk-js/1.0.18 KiroIDE-0.6.18"

KIRO_CLI_USER_AGENT = "aws-sdk-rust/1.3.9 os/macos lang/rust/1.87.0"
KIRO_CLI_AMZ_USER_AGENT = "aws-sdk-rust/1.3.9 ua/2.1 api/ssooidc/1.88.0 os/macos lang/rust/1.87.0 m/E app/AmazonQ-For-CLI"

AGENT_MODE_SPEC = "spec"
AGENT_MODE_VIBE = "vibe"

# Targets (AWS-style)
CODEWHISPERER_AMZ_TARGET = (
    "AmazonCodeWhispererStreamingService.GenerateAssistantResponse"
)
AMAZONQ_AMZ_TARGET = "AmazonQDeveloperStreamingService.SendMessage"
