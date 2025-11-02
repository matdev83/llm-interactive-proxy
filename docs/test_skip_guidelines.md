# Test Skip Condition Guidelines

This document provides guidelines for when and how to use skip conditions in tests within the LLM Interactive Proxy project.

## Legitimate Skip Conditions

### 1. Platform-Specific Tests
Tests that can only run on specific operating systems:

```python
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
@pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
@pytest.mark.skipif(platform.system() == "Windows", reason="Unix-specific test")
```

**When to use:**
- Testing Windows-specific APIs (e.g., `ctypes.windll`)
- Testing platform-specific path behavior (drive letters, UNC paths, case sensitivity)
- Testing Unix-specific functionality (symlinks, Unix permissions)

### 2. External Dependency Tests
Tests that require external services, credentials, or tools:

```python
# API keys/credentials
@pytest.mark.skipif(not _has_api_key(), reason="API key not available")

# External tools
@pytest.mark.skipif(not _check_tool_installed(), reason="Tool not installed")

# Network connectivity
@pytest.mark.skipif(not _can_connect_to_service(), reason="Service unavailable")
```

**When to use:**
- Integration tests requiring real API credentials
- Tests depending on external CLI tools
- Tests requiring network connectivity to external services

### 3. Optional Dependency Tests
Tests that require optional dependencies:

```python
@pytest.mark.skipif(not _dependency_available(), reason="Optional dependency not installed")
```

**When to use:**
- Tests for features enhanced by optional libraries
- Tests that require specific versions of dependencies

## Prohibited Skip Conditions

### 1. Hardcoded False Conditions
```python
# NEVER DO THIS
@pytest.mark.skipif(False, reason="TODO: Implement feature")
```

### 2. Non-Existent CLI Flags
```python
# NEVER DO THIS
pytestmark = pytest.mark.skip(reason="Run with --non-existent-flag to enable")
```

### 3. Permanent Skips
```python
# NEVER DO THIS
def _check_feature() -> bool:
    return False  # Always returns False
```

## Skip Condition Best Practices

### 1. Use Environment Variables for Conditional Testing
Instead of hardcoded skips, use environment variables:

```python
def _check_experimental_feature() -> bool:
    return os.environ.get("ENABLE_EXPERIMENTAL_TESTS") == "1"

@pytest.mark.skipif(not _check_experimental_feature(), reason="Set ENABLE_EXPERIMENTAL_TESTS=1 to enable")
```

### 2. Provide Clear Instructions
Skip reasons should include actionable instructions:

```python
@pytest.mark.skipif(not _has_credentials(), reason="Run 'gemini login' to authenticate")
```

### 3. Use Feature Gates Appropriately
For experimental features, use feature flags:

```python
@pytest.mark.skipif(not config.FEATURE_ENABLED, reason="Experimental feature - set FEATURE_ENABLED=true")
```

### 4. Test Skip Condition Logic
Ensure skip condition functions work correctly:

```python
def _check_tool_available() -> bool:
    try:
        subprocess.run(["tool", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
```

## Review Process

### For PR Reviewers
1. **Question all hardcoded skips** - Ask `False` skip conditions to be removed or justified
2. **Verify CLI flags exist** - Ensure any referenced CLI flags are implemented
3. **Check for TODO reasons** - TODO items should not be permanent skip reasons
4. **Validate skip logic** - Skip condition functions should work as intended

### For Developers
1. **Document skip reasons** - Provide clear, actionable skip reasons
2. **Use environment variables** - Make experimental features testable via env vars
3. **Consider alternatives** - Use mocks instead of skips when possible
4. **Remove obsolete skips** - Clean up skip conditions when features are implemented

## Regular Audits

### Monthly Skip Condition Audit
1. Search for `skipif(False,` patterns
2. Search for `--run-.*` flag references in skip reasons
3. Verify all skip conditions are still relevant
4. Remove or fix any problematic skips

### CI/CD Integration
Consider adding a CI check that flags:
- Hardcoded `False` skip conditions
- References to non-existent CLI flags
- Skip conditions that have been in place for > 3 months

## Examples

### Good Skip Condition
```python
def _check_docker_available() -> bool:
    try:
        subprocess.run(["docker", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

@pytest.mark.skipif(not _check_docker_available(), reason="Docker not installed - see docs.docker.com")
```

### Bad Skip Condition
```python
@pytest.mark.skipif(False, reason="TODO: Implement Docker integration")
```

## Enforcement

These guidelines will be enforced through:
1. **PR review process** - Reviewers must validate skip conditions
2. **Regular audits** - Monthly checks for problematic skips
3. **CI validation** - Automated checks for obvious anti-patterns