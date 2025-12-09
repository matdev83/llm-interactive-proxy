# Test Failures Fix Plan

## Issues Summary
- [ ] 1. Documentation Index Issue - `inline-python-steering.md` not listed in user_guide/index.md
- [ ] 2. Ruff Linting Issues - F821 and RUF005 violations  
- [ ] 3. DI Container Violations - CommandExtractionService direct instantiation
- [ ] 4. MyPy Type Checking Issues - ConfiguredRulesPolicy undefined and union attribute

## Implementation Steps

### Phase 1: Fix Overlapping Issues (High Priority)
- [ ] 1.1 Fix undefined `ConfiguredRulesPolicy` in steering.py:160
- [ ] 1.2 Fix mypy union attribute issue in unified_tool_security_handler.py:274
- [ ] 1.3 Fix ruff concatenation issue in unified_security_config.py:86

### Phase 2: Fix DI Container Violations
- [ ] 2.1 Fix CommandExtractionService instantiation in inline_python_steering_handler.py:59
- [ ] 2.2 Fix CommandExtractionService instantiation in inline_python_policy.py:48

### Phase 3: Fix Documentation Issues
- [ ] 3.1 Add missing `inline-python-steering.md` link to user_guide/index.md

### Phase 4: Verification
- [ ] 4.1 Run ruff linting test to verify fixes
- [ ] 4.2 Run mypy validation test to verify fixes
- [ ] 4.3 Run DI container test to verify fixes
- [ ] 4.4 Run documentation structure test to verify fixes
- [ ] 4.5 Run all failing tests together to confirm complete resolution

## Files to Modify
1. `src/core/app/stages/steering.py` - Fix ConfiguredRulesPolicy import
2. `src/core/services/unified_tool_security_handler.py` - Fix union attribute
3. `src/core/domain/configuration/unified_security_config.py` - Fix concatenation
4. `src/core/services/tool_call_handlers/inline_python_steering_handler.py` - Fix DI violation
5. `src/services/steering/policies/inline_python_policy.py` - Fix DI violation
6. `docs/user_guide/index.md` - Add missing documentation link
