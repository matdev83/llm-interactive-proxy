# Test Failures Fix Checklist

## Test Failures Identified:
1. **test_documentation_structure.py** - `inline-python-steering.md` not listed in user_guide/index.md
2. **test_cli.py** - PytestFullSuiteHandler should be registered
3. **test_di_container_usage.py** - DI container violations detected
4. **test_mypy_validation.py** - mypy type checking failed on src directory

## Implementation Steps:

### 1. Documentation Structure Fix
- [ ] 1.1 Examine test_documentation_structure.py to understand the requirement
- [ ] 1.2 Check if inline-python-steering.md exists in user_guide/
- [ ] 1.3 Update user_guide/index.md to include inline-python-steering.md
- [ ] 1.4 Re-run test_documentation_structure.py to verify fix

### 2. CLI Handler Registration Fix
- [ ] 2.1 Examine test_cli.py to understand what PytestFullSuiteHandler should be
- [ ] 2.2 Check current CLI flag configuration and handlers
- [ ] 2.3 Add or fix PytestFullSuiteHandler registration
- [ ] 2.4 Re-run test_cli.py to verify fix

### 3. DI Container Violations Fix
- [ ] 3.1 Examine test_di_container_usage.py to understand violations
- [ ] 3.2 Run the DI container violation detection
- [ ] 3.3 Fix the identified DI container violations
- [ ] 3.4 Re-run test_di_container_usage.py to verify fix

### 4. MyPy Validation Fix
- [ ] 4.1 Run mypy validation to see specific type errors
- [ ] 4.2 Fix type annotations and type checking issues
- [ ] 4.3 Re-run mypy validation to ensure all issues are resolved
- [ ] 4.4 Re-run test_mypy_validation.py to verify fix

### 5. Final Verification
- [ ] 5.1 Run all failing tests individually to confirm fixes
- [ ] 5.2 Run full test suite to ensure no regressions
- [ ] 5.3 Clean up any temporary files created during debugging

## Notes:
- Use Windows venv interpreter: ./.venv/Scripts/python.exe
- Focus on one test at a time for systematic debugging
- Document any configuration changes needed
