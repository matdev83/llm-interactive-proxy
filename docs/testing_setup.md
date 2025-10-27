# Test Environment Setup Guide

## Overview

This guide provides comprehensive instructions for setting up the test environment for the LLM Interactive Proxy project. The testing environment supports multiple scenarios ranging from basic unit testing to full integration testing with real API calls.

### Testing Scenarios

- **Unit Testing**: Fast, isolated tests with no external dependencies
- **Integration Testing with Mocks**: Tests using mocked backends and responses
- **Integration Testing with Real APIs**: Tests requiring actual API keys and external services
- **End-to-End Testing**: Full system tests with real external tools and services

## Quick Start

For basic unit testing, no additional setup is required:

```bash
# Activate virtual environment
.\.venv\Scripts\activate

# Run unit tests only
./.venv/Scripts/python.exe -m pytest tests/unit/ -v
```

For integration testing with real APIs, follow the detailed setup instructions below.

## Unit Testing

Unit tests focus on testing individual components in isolation without external dependencies.

### Requirements
- Python virtual environment (`.venv`)
- Project dependencies installed

### Setup
```bash
# Activate virtual environment
.\.venv\Scripts\activate

# Install dependencies
./.venv/Scripts/python.exe -m pip install -e .[dev]

# Run unit tests
./.venv/Scripts/python.exe -m pytest tests/unit/ -v
```

### What Unit Tests Cover
- Command parsing and processing
- Configuration management
- Backend factory and service logic
- Authentication and session management
- Response processing and error handling
- Core domain logic and utilities

## Integration Testing

Integration tests verify that different components work together correctly. This project supports two levels of integration testing.

### Integration Testing with Mock Backends

These tests use mocked responses and don't require external API keys or services.

```bash
# Run integration tests with mocks
./.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "not network"
```

**What These Tests Cover:**
- Server startup and basic functionality
- Request/response processing through the proxy
- Backend routing and failover logic
- Session management and state handling
- Error recovery and graceful degradation

### Integration Testing with Real APIs

These tests require actual API keys and external service access.

#### API Key Requirements

The following environment variables must be set for different backends:

##### Gemini API Keys
```bash
# Primary Gemini API key
export GEMINI_API_KEY="your_gemini_api_key_here"

# Additional numbered Gemini keys (for rotation/failover testing)
export GEMINI_API_KEY_1="your_gemini_api_key_1_here"
export GEMINI_API_KEY_2="your_gemini_api_key_2_here"
# ... up to GEMINI_API_KEY_20
```

##### OpenAI/OpenRouter API Keys
```bash
# OpenAI API key (for direct OpenAI calls)
export OPENAI_API_KEY="your_openai_api_key_here"

# OpenRouter API key (recommended for broader model access)
export OPENROUTER_API_KEY="your_openrouter_api_key_here"
export OPENROUTER_API_KEY_1="your_openrouter_api_key_1_here"
export OPENROUTER_API_KEY_2="your_openrouter_api_key_2_here"
# ... up to OPENROUTER_API_KEY_20
```

##### Anthropic API Keys
```bash
# Anthropic API key for Claude models
export ANTHROPIC_API_KEY="your_anthropic_api_key_here"
export ANTHROPIC_API_KEY_1="your_anthropic_api_key_1_here"
export ANTHROPIC_API_KEY_2="your_anthropic_api_key_2_here"
# ... up to ANTHROPIC_API_KEY_20
```

##### Additional API Keys
```bash
# ZAI (Zhipu AI) backend
export ZAI_API_KEY="your_zai_api_key_here"

# Google Cloud Project (for OAuth-based backends)
export GOOGLE_CLOUD_PROJECT="your_gcp_project_id"
```

#### Setting Up API Keys

**Option 1: Environment Variables (Recommended for Testing)**
```bash
# Add to your shell profile or .bashrc/.zshrc
export GEMINI_API_KEY="your_key_here"
export OPENROUTER_API_KEY="your_key_here"
export ANTHROPIC_API_KEY="your_key_here"
```

**Option 2: .env File (Local Development)**
Create a `.env` file in the project root:
```bash
# .env file
GEMINI_API_KEY=your_gemini_key_here
OPENROUTER_API_KEY=your_openrouter_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
```

**Option 3: System Environment (CI/CD)**
Set environment variables in your CI/CD system configuration.

#### Running Integration Tests with Real APIs

```bash
# Run all integration tests (requires API keys)
./.venv/Scripts/python.exe -m pytest tests/integration/ -v

# Run specific integration tests
./.venv/Scripts/python.exe -m pytest tests/integration/test_gemini_end_to_end.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_models_endpoints.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_anthropic_backend.py -v

# Run tests with network access only
./.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "network"
```

## External Tools Setup

### Gemini CLI (Optional)

Required for `test_gemini_cli_acp_integration.py` and related gemini-cli-acp backend functionality.

#### Installation
```bash
# Install globally via npm
npm install -g @google/gemini-cli
```

#### Authentication
```bash
# Authenticate with Google account
gemini login
```

#### Verification
```bash
# Check if gemini-cli is available and authenticated
gemini --version

# Verify authentication (check for credentials file)
ls ~/.gemini/oauth_creds.json
```

#### Configuration

**Project Directory Setup:**
The gemini-cli backend can use different project directories:

1. **Via Environment Variable:**
```bash
export GEMINI_CLI_WORKSPACE="/path/to/your/project"
```

2. **Via Configuration File:**
Edit `config/backends/gemini-cli-acp/backend.yaml`:
```yaml
project_dir: "/path/to/your/project"
```

3. **Runtime via Commands:**
Use `!/project-dir(/path/to/project)` during runtime.

#### Running Gemini CLI Tests

```bash
# Run gemini-cli integration tests (requires gemini-cli setup)
./.venv/Scripts/python.exe -m pytest tests/integration/test_gemini_cli_acp_integration.py -v -s
```

**Note:** These tests are currently experimental and may be skipped if gemini-cli ACP mode is not working reliably.

### Qwen OAuth Setup (Optional)

Required for Qwen OAuth backend integration tests.

#### OAuth Credentials Setup

The Qwen OAuth backend uses credentials stored in:
```
~/.qwen/oauth_creds.json
```

This file should contain:
```json
{
  "access_token": "your_access_token",
  "refresh_token": "your_refresh_token",
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

**Note:** Qwen OAuth integration tests are currently disabled by default to prevent browser OAuth flows. To enable:
```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_qwen_oauth_integration.py -v --run-qwen-oauth
```

## Testing Workflow

### Recommended Testing Sequence

1. **Start with Unit Tests:**
```bash
./.venv/Scripts/python.exe -m pytest tests/unit/ -v
```

2. **Run Integration Tests with Mocks:**
```bash
./.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "not network"
```

3. **Run Integration Tests with Real APIs (if keys available):**
```bash
./.venv/Scripts/python.exe -m pytest tests/integration/ -v -m "network"
```

4. **Run Specific Integration Tests:**
```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_gemini_end_to_end.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_server_smoke.py -v
```

### Test Markers

The project uses pytest markers to categorize tests:

- `unit`: Unit tests
- `integration`: Integration tests
- `network`: Tests requiring network access
- `no_global_mock`: Tests that should not use global mocks
- `asyncio`: Async tests
- `httpx_mock`: Tests requiring httpx mocking

### Running Tests by Category

```bash
# Run only unit tests
./.venv/Scripts/python.exe -m pytest -m "unit"

# Run integration tests only
./.venv/Scripts/python.exe -m pytest -m "integration"

# Run network tests only
./.venv/Scripts/python.exe -m pytest -m "network"

# Run tests excluding network tests
./.venv/Scripts/python.exe -m pytest -m "not network"

# Run tests with specific markers
./.venv/Scripts/python.exe -m pytest -m "integration and network"
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Missing API Keys

**Symptom:** Tests are skipped with messages like "API key not found"

**Solution:**
```bash
# Check which environment variables are set
env | grep -E "(GEMINI_|OPENROUTER_|ANTHROPIC_)" | sort

# Set missing API keys
export GEMINI_API_KEY="your_actual_key_here"
export OPENROUTER_API_KEY="your_actual_key_here"
```

#### 2. gemini-cli Not Available

**Symptom:** `test_gemini_cli_acp_integration.py` tests are skipped

**Solution:**
```bash
# Install gemini-cli
npm install -g @google/gemini-cli

# Verify installation
gemini --version

# Authenticate
gemini login

# Check credentials
ls ~/.gemini/oauth_creds.json
```

#### 3. OAuth Credentials Missing (Qwen)

**Symptom:** Qwen OAuth tests fail or are skipped

**Solution:**
- Ensure `~/.qwen/oauth_creds.json` exists and contains valid tokens
- Re-run OAuth flow if credentials are expired
- Note: These tests are disabled by default

#### 4. Port Conflicts

**Symptom:** Server startup tests fail with "Address already in use"

**Solution:**
```bash
# Find process using the port
netstat -ano | findstr :8000  # Windows
lsof -i :8000  # Linux/Mac

# Kill the process if needed
taskkill /PID <process_id> /F  # Windows
kill -9 <process_id>  # Linux/Mac
```

#### 5. Network Timeouts

**Symptom:** Integration tests timeout when calling external APIs

**Solutions:**
- Check internet connectivity
- Verify API keys are valid and have sufficient quota
- Check firewall/proxy settings
- Increase timeout values in test configuration

#### 6. Virtual Environment Issues

**Symptom:** Import errors or "python not found" errors

**Solution:**
```bash
# Activate virtual environment
.\.venv\Scripts\activate

# Reinstall dependencies
./.venv/Scripts/python.exe -m pip install -e .[dev]

# Verify installation
./.venv/Scripts/python.exe -c "import src; print('Success')"
```

#### 7. Test Collection Errors

**Symptom:** Tests fail to collect or import errors

**Solutions:**
```bash
# Check Python path
./.venv/Scripts/python.exe -c "import sys; print(sys.path)"

# Run from project root
cd c:/Users/Mateusz/source/repos/llm-interactive-proxy

# Verify project structure
ls -la src/ tests/ config/
```

### Debug Mode

Run tests with verbose output for debugging:

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
./.venv/Scripts/python.exe -m pytest tests/integration/test_specific_test.py -v -s --log-level=DEBUG

# Run with pdb debugger on failure
./.venv/Scripts/python.exe -m pytest tests/integration/test_specific_test.py -v -s --pdb

# Run with more verbose output
./.venv/Scripts/python.exe -m pytest tests/integration/test_specific_test.py -vvv -s
```

### Environment Verification

Use this script to verify your test environment:

```bash
#!/bin/bash
# verify_test_env.sh

echo "=== Python Environment ==="
which python
python --version

echo -e "\n=== Virtual Environment ==="
echo "VIRTUAL_ENV: $VIRTUAL_ENV"

echo -e "\n=== API Keys ==="
env | grep -E "(GEMINI_|OPENROUTER_|ANTHROPIC_)" | sort

echo -e "\n=== gemini-cli ==="
if command -v gemini &> /dev/null; then
    echo "gemini-cli installed: $(gemini --version)"
    if [ -f ~/.gemini/oauth_creds.json ]; then
        echo "gemini-cli authenticated: Yes"
    else
        echo "gemini-cli authenticated: No"
    fi
else
    echo "gemini-cli not installed"
fi

echo -e "\n=== Qwen OAuth ==="
if [ -f ~/.qwen/oauth_creds.json ]; then
    echo "Qwen OAuth credentials found"
else
    echo "Qwen OAuth credentials not found"
fi

echo -e "\n=== Test Project Structure ==="
ls -la src/ tests/ config/ 2>/dev/null || echo "Project structure incomplete"
```

## Reference

### Key Test Files and Their Requirements

#### Unit Tests (`tests/unit/`)

- **`test_config.py`**: Configuration loading and validation
- **`test_backend_factory.py`**: Backend factory and service creation
- **`test_auth.py`**: Authentication logic and session management
- **`test_cli.py`**: Command-line interface and argument parsing
- **`test_command_parser.py`**: Command parsing and processing

#### Integration Tests (`tests/integration/`)

##### Network-Required Tests

- **`test_gemini_end_to_end.py`**:
  - Requires: `GEMINI_API_KEY` or `GEMINI_API_KEY_1`
  - Tests: Full Gemini backend integration
  
- **`test_models_endpoints.py`**:
  - Requires: At least one API key (any backend)
  - Tests: Model discovery and endpoint functionality

- **`test_anthropic_backend.py`**:
  - Requires: `ANTHROPIC_API_KEY`
  - Tests: Anthropic Claude integration

- **`test_gemini_cli_acp_integration.py`**:
  - Requires: gemini-cli installed and authenticated
  - Tests: Gemini CLI Agent Client Protocol integration

- **`test_server_smoke.py`**:
  - Requires: Minimal setup (creates dummy keys)
  - Tests: Server startup and basic health checks

##### Mock-Based Integration Tests

- **`test_app.py`**: Application startup and basic routing
- **`test_proxy_logic.py`**: Proxy request/response handling
- **`test_failover_routes.py`**: Backend failover logic
- **`test_empty_response_handling.py`**: Error recovery mechanisms

#### Configuration Files

- **`config/config.example.yaml`**: Example configuration with all options
- **`config/backends/gemini-cli-acp/backend.yaml`**: Gemini CLI backend configuration
- **`config/backends/qwen-oauth/backend.yaml`**: Qwen OAuth backend configuration
- **`pyproject.toml`**: Project dependencies and test configuration

#### Test Configuration

Pytest configuration in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "unit: Unit tests",
    "integration: Integration tests", 
    "network: Tests requiring network access",
    "no_global_mock: Tests that should not use global mocks"
]
```

### Environment Variable Reference

| Variable | Description | Used By |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Primary Gemini API key | Gemini backend tests |
| `GEMINI_API_KEY_1-20` | Additional Gemini keys | Key rotation/failover tests |
| `OPENAI_API_KEY` | OpenAI API key | OpenAI backend tests |
| `OPENROUTER_API_KEY` | Primary OpenRouter key | OpenRouter backend tests |
| `OPENROUTER_API_KEY_1-20` | Additional OpenRouter keys | Key rotation/failover tests |
| `ANTHROPIC_API_KEY` | Primary Anthropic key | Anthropic backend tests |
| `ANTHROPIC_API_KEY_1-20` | Additional Anthropic keys | Key rotation/failover tests |
| `ZAI_API_KEY` | ZAI backend key | ZAI backend tests |
| `GOOGLE_CLOUD_PROJECT` | GCP project for OAuth | OAuth-based backends |
| `GEMINI_CLI_WORKSPACE` | Workspace for gemini-cli | Gemini CLI tests |

### Best Practices

1. **Start Simple**: Begin with unit tests, progress to integration tests
2. **Use Markers**: Categorize tests appropriately for selective execution
3. **Environment Isolation**: Use virtual environments and clear API key management
4. **Incremental Testing**: Test individual components before full integration
5. **Debug Strategically**: Use appropriate logging and debugging tools
6. **Clean State**: Ensure test environment is clean between test runs
7. **Key Rotation**: Use multiple API keys for failover testing when available

This documentation should reduce setup time for developers and improve consistency across the testing environment.