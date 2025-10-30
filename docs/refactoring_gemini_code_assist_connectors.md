# Refactoring Gemini Code Assist Connectors - DRY Principle

## Problem Statement

Currently, the Gemini Code Assist API system message handling logic (the 64K `systemInstruction` limit fix) is duplicated across three separate files:

1. **`src/connectors/gemini_oauth_base.py`** (lines 1800-1841, 2000-2041 for streaming)
   - Used by `gemini-oauth-plan` and `gemini-oauth-free`
2. **`src/connectors/gemini_cloud_project.py`** (lines 1115-1156, 1260-1301 for streaming)
   - Used by `gemini-cloud-project`

This violates the DRY (Don't Repeat Yourself) principle and creates maintenance risk - as evidenced by having to fix the same 64K token limit bug in multiple places.

## Current Architecture

```
GeminiBackend (base class)
├── GeminiOAuthBaseConnector (abstract base for OAuth connectors)
│   ├── GeminiOAuthFreeConnector (free-tier, auto-managed project)
│   └── GeminiOAuthPlanConnector (paid plans, auto-managed project)
└── GeminiCloudProjectConnector (user's own GCP project)
```

### Key Differences Between Connectors:

| Aspect | GeminiOAuthBase | GeminiCloudProject |
|--------|-----------------|-------------------|
| **Authentication** | OAuth with `~/.gemini/oauth_creds.json` | OAuth with `~/.gemini/client_config.json` or ADC |
| **Project Source** | Auto-discovered from onboarding API | User-specified via `GOOGLE_CLOUD_PROJECT` |
| **Onboarding** | Calls onboarding API with tier selection | Calls onboarding API with user's project ID |
| **Billing** | Google-managed (free or paid plan) | User's GCP project |
| **Project Discovery** | `_discover_project_id()` method | `_ensure_project_onboarded()` method |

### Duplicated Code Sections:

**System Message Conversion (IDENTICAL in both):**
```python
# Lines 1800-1841 in oauth_base.py
# Lines 1115-1156 in cloud_project.py

# Code Assist API doesn't support 'system' role in contents array
# KiloCode's approach: Put system messages as FIRST user message in contents
# This avoids the 64K token limit on the separate systemInstruction field
system_instruction_parts: list[dict[str, Any]] = []
filtered_contents = []

for content in gemini_request.get("contents", []):
    if content.get("role") == "system":
        # Collect all system message parts
        parts = content.get("parts", [])
        if isinstance(parts, list):
            system_instruction_parts.extend(parts)
        elif parts:
            system_instruction_parts.append(parts)
    else:
        filtered_contents.append(content)

# Prepend system messages as first user message (KiloCode's approach)
# This avoids hitting the 64K limit on systemInstruction field
final_contents = []
if system_instruction_parts:
    final_contents.append(
        {
            "role": "user",
            "parts": system_instruction_parts,
        }
    )
final_contents.extend(filtered_contents)

# Build the request for Code Assist API
code_assist_request = {
    "contents": final_contents,
    "generationConfig": gemini_request.get("generationConfig", {}),
}

# Add other fields if present
if "tools" in gemini_request:
    code_assist_request["tools"] = gemini_request["tools"]
if "toolConfig" in gemini_request:
    code_assist_request["toolConfig"] = gemini_request["toolConfig"]
if "safetySettings" in gemini_request:
    code_assist_request["safetySettings"] = gemini_request["safetySettings"]
```

This EXACT same code block appears in:
- `_chat_completions_code_assist()` (non-streaming)
- `_chat_completions_code_assist_streaming()` (streaming)

In BOTH `gemini_oauth_base.py` AND `gemini_cloud_project.py`!

**That's 4 copies of the same 40+ lines of critical bug-fix code!**

## Proposed Solution: GeminiCodeAssistMixin

Create a mixin class that contains all shared Code Assist API logic, leaving only authentication and project management differences in the concrete classes.

### New Architecture

```
GeminiBackend (base class)
├── GeminiCodeAssistMixin (NEW - shared Code Assist API logic)
│   └── Methods:
│       ├── _convert_system_messages_for_code_assist()  # NEW - extracts the duplicated logic
│       ├── _build_code_assist_request()                # NEW - builds the request structure
│       └── Abstract methods:
│           ├── _get_auth_session()                     # To be implemented by subclasses
│           └── _get_project_id()                       # To be implemented by subclasses
│
├── GeminiOAuthBaseConnector (uses mixin)
│   ├── Implements: _get_auth_session(), _get_project_id()
│   ├── GeminiOAuthFreeConnector
│   └── GeminiOAuthPlanConnector
│
└── GeminiCloudProjectConnector (uses mixin)
    └── Implements: _get_auth_session(), _get_project_id()
```

### Refactoring Steps

#### Step 1: Create GeminiCodeAssistMixin

Create `src/connectors/mixins/gemini_code_assist_mixin.py`:

```python
"""
Mixin for shared Gemini Code Assist API logic.

This mixin contains the common logic for handling the Code Assist API,
including the fix for the 64K systemInstruction token limit.
"""

class GeminiCodeAssistMixin:
    """Shared logic for Gemini Code Assist API requests."""
    
    def _convert_system_messages_for_code_assist(
        self, gemini_request: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert system messages to KiloCode's approach (first user message).
        
        This method implements the fix for the 64K systemInstruction token limit
        by prepending system messages as the first user message in the contents array.
        
        Args:
            gemini_request: Gemini-formatted request with potentially system role messages
            
        Returns:
            Final contents array with system messages converted to first user message
        """
        # [Move the duplicated 40+ lines here]
        
    def _build_code_assist_request(
        self, 
        gemini_request: dict[str, Any],
        final_contents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build Code Assist API request structure.
        
        Args:
            gemini_request: Original Gemini request
            final_contents: Processed contents with system messages converted
            
        Returns:
            Code Assist API request dict
        """
        # [Move the request building logic here]
```

#### Step 2: Refactor GeminiOAuthBaseConnector

Update `src/connectors/gemini_oauth_base.py`:

```python
from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin

class GeminiOAuthBaseConnector(GeminiBackend, GeminiCodeAssistMixin, abc.ABC):
    """Base class for Gemini OAuth connectors."""
    
    # Remove duplicated code, use mixin methods instead:
    async def _chat_completions_code_assist(self, ...):
        # ... auth setup ...
        
        # Use mixin method instead of duplicated code
        final_contents = self._convert_system_messages_for_code_assist(gemini_request)
        code_assist_request = self._build_code_assist_request(gemini_request, final_contents)
        
        # ... rest of the method ...
```

#### Step 3: Refactor GeminiCloudProjectConnector

Update `src/connectors/gemini_cloud_project.py`:

```python
from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin

class GeminiCloudProjectConnector(GeminiBackend, GeminiCodeAssistMixin):
    """Connector for user's own GCP project."""
    
    # Remove duplicated code, use mixin methods instead:
    async def _chat_completions_standard(self, ...):
        # ... auth setup ...
        
        # Use mixin method instead of duplicated code
        final_contents = self._convert_system_messages_for_code_assist(gemini_request)
        code_assist_request = self._build_code_assist_request(gemini_request, final_contents)
        
        # ... rest of the method ...
```

### Benefits of This Refactoring

1. ✅ **DRY Principle**: Critical logic exists in ONE place only
2. ✅ **Maintainability**: Future fixes only need to be applied once
3. ✅ **Testability**: Can test the mixin logic independently
4. ✅ **Clarity**: Clear separation between shared and connector-specific logic
5. ✅ **Safety**: Regression tests protect against breaking changes
6. ✅ **Flexibility**: Easy to add new Code Assist connectors in the future

### Testing Strategy

1. **Run existing regression tests**: `test_gemini_64k_systeminstruction_limit.py`
2. **Run connector-specific tests**: Ensure no behavioral changes
3. **Run full test suite**: Verify no side effects
4. **Manual testing**: Test with real KiloCode agent if available

### Risks and Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking existing functionality | Comprehensive test suite runs before/after |
| Multiple inheritance complexity | Python's MRO (Method Resolution Order) handles this cleanly |
| Performance impact | No performance impact - just code organization |
| Regression in authentication | Each connector maintains its own auth logic |

## Implementation Checklist

- [ ] Create `src/connectors/mixins/` directory
- [ ] Create `src/connectors/mixins/__init__.py`
- [ ] Create `src/connectors/mixins/gemini_code_assist_mixin.py` with mixin class
- [ ] Extract `_convert_system_messages_for_code_assist()` method
- [ ] Extract `_build_code_assist_request()` method
- [ ] Update `GeminiOAuthBaseConnector` to use mixin
- [ ] Update `GeminiCloudProjectConnector` to use mixin
- [ ] Run `test_gemini_64k_systeminstruction_limit.py` - should pass unchanged
- [ ] Run full test suite
- [ ] Update this documentation with final implementation details

## References

- Original bug fix commit: `de251c3f`
- Regression tests: `tests/unit/connectors/test_gemini_64k_systeminstruction_limit.py`
- KiloCode reference: `dev/thrdparty/kilocode/src/api/providers/gemini-cli.ts:292-298`
- Documentation: `docs/gemini_code_assist_parameters.md`

