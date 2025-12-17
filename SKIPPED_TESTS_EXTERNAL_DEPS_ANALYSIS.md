# Analysis: Tests Skipped Due to External Tools and Files

## Summary

After analyzing tests that skip due to "external tools" and "missing files/data", here's what I found:

- **cbor2**: ✅ **INSTALLED** - Listed in `pyproject.toml` (line 34: `cbor2>=5.6.0`) and importable
- **gemini-cli**: ✅ **AVAILABLE** - Found at `/home/mateusz/.nvm/versions/node/v24.4.0/bin/gemini`
- **Capture files**: ⚠️ **MISSING** - `var/wire_captures_cbor/` directory exists but is empty (only `.gitkeep`)

## Detailed Analysis

### 1. Tests Requiring `cbor2` Package

#### Status: ✅ **SHOULD NOT BE SKIPPED** - Package is installed

**cbor2 is a required dependency:**
- Listed in `pyproject.toml` line 34: `"cbor2>=5.6.0"`
- Successfully importable: `import cbor2` works
- Used throughout the codebase for CBOR wire capture functionality

#### Tests That Skip Due to cbor2:

1. **`tests/unit/core/ports/test_usage_chunk_cbor_replay.py`**
   - **Line 42:** `pytest.skip("cbor2 not installed")` in `load_cbor_entries()` function
   - **Analysis:** This skip will **NEVER trigger** if dependencies are properly installed. The check is defensive but unnecessary since cbor2 is a required dependency.
   - **Recommendation:** Remove the skip check OR make it fail the test instead of skipping (since cbor2 is required)

2. **`tests/codex/integration/test_droid_codex_compatibility.py`**
   - **Line 180:** `@pytest.mark.skipif(cbor2 is None, reason="cbor2 not installed")`
   - **Analysis:** Same as above - cbor2 is required, so this skipif will never trigger.
   - **Recommendation:** Remove the skipif decorator OR change to `pytest.fail()` if cbor2 is missing

#### Code Locations:

```python
# tests/unit/core/ports/test_usage_chunk_cbor_replay.py:37-42
def load_cbor_entries(capture_file: Path) -> list[dict[str, Any]]:
    """Load entries from CBOR capture file."""
    try:
        import cbor2
    except ImportError:
        pytest.skip("cbor2 not installed")  # ⚠️ Will never trigger if deps installed
```

```python
# tests/codex/integration/test_droid_codex_compatibility.py:180
@pytest.mark.skipif(cbor2 is None, reason="cbor2 not installed")  # ⚠️ Will never trigger
def test_load_captured_tools_from_cbor(self):
```

### 2. Tests Requiring `gemini-cli` Tool

#### Status: ✅ **AVAILABLE** - Tool is installed

**gemini-cli is an external npm tool:**
- Found at: `/home/mateusz/.nvm/versions/node/v24.4.0/bin/gemini`
- Not a Python package, but an external CLI tool installed via npm
- Used for testing the `gemini-cli-acp` backend connector

#### Tests That Skip Due to gemini-cli:

**`tests/integration/test_gemini_cli_acp_integration.py`**
- **Lines 237-248:** Multiple `@pytest.mark.skipif` decorators checking:
  1. `_check_gemini_cli_available()` - checks if `gemini --version` works
  2. `_check_gemini_cli_authenticated()` - checks if gemini-cli is logged in
  3. `_check_gemini_cli_acp_working()` - checks if ACP mode works
- **Lines 544, 546:** Runtime skips for same conditions

**Analysis:**
- ✅ **Legitimate skips** - These are integration tests that require:
  1. External npm tool (`gemini-cli`) to be installed
  2. User to be authenticated with `gemini login`
  3. Experimental ACP feature to be working
- These are **optional integration tests** that test real external tool integration
- The skips are **correct** - not everyone will have gemini-cli installed/configured

**Recommendation:** ✅ **KEEP AS IS** - These are legitimate conditional skips for optional external tool integration.

### 3. Tests Requiring Capture Files/Data

#### Status: ⚠️ **MISSING DATA** - Directory exists but is empty

**Wire captures directory:**
- Path: `var/wire_captures_cbor/`
- Status: Exists but empty (only contains `.gitkeep`)
- Purpose: Contains CBOR-encoded wire captures from actual proxy sessions
- These are **runtime-generated data files**, not source files

#### Tests That Skip Due to Missing Capture Files:

1. **`tests/unit/core/ports/test_usage_chunk_cbor_replay.py`**
   - **Line 208:** `pytest.skip("No CBOR capture files available for replay testing")`
   - **Line 217:** `pytest.skip("No stop chunks with usage found in captures")`
   - **Analysis:** ✅ **Legitimate skip** - Tests replay real captured data. If no captures exist, there's nothing to test.
   - **Recommendation:** ✅ **KEEP AS IS** - These are regression tests using real-world data

2. **`tests/codex/integration/test_droid_codex_compatibility.py`**
   - **Line 190:** `pytest.skip("No wire captures directory")`
   - **Line 195:** `pytest.skip("No Droid capture files found")`
   - **Line 232:** `pytest.skip(f"Could not load capture: {e}")`
   - **Analysis:** ✅ **Legitimate skip** - Tests require specific Droid capture files (`proxy-20251205*.cbor`)
   - **Recommendation:** ✅ **KEEP AS IS** - These are integration tests requiring specific captured data

3. **`tests/simulation/test_gemini_antigravity_regression.py`**
   - **Line 30:** `pytest.skip(f"Capture file not found: {CAPTURE_FILE}")`
   - **Line 65:** `@pytest.mark.skip(reason="Requires specific complex capture file")`
   - **Line 271:** `pytest.skip(f"Capture file not found: {CAPTURE_FILE}")`
   - **Analysis:** ✅ **Legitimate skip** - Regression tests requiring specific capture files
   - **Recommendation:** ✅ **KEEP AS IS** - These test specific regression scenarios

## Recommendations Summary

### ✅ Keep Skipped (Legitimate):

1. **gemini-cli tests** - External tool integration, optional
2. **Capture file tests** - Require runtime-generated data files

### ⚠️ Fix Skip Logic (Unnecessary):

1. **cbor2 checks** - Since cbor2 is a **required dependency**, the skip checks will never trigger if dependencies are properly installed. Consider:
   - **Option A:** Remove skip checks entirely (let ImportError fail the test if cbor2 is missing)
   - **Option B:** Change skip to `pytest.fail()` to indicate missing required dependency
   - **Option C:** Keep as defensive check but add comment explaining it's defensive

### 📝 Specific Actions:

#### For `tests/unit/core/ports/test_usage_chunk_cbor_replay.py`:

```python
# Current (line 37-42):
def load_cbor_entries(capture_file: Path) -> list[dict[str, Any]]:
    """Load entries from CBOR capture file."""
    try:
        import cbor2
    except ImportError:
        pytest.skip("cbor2 not installed")  # ⚠️ Unnecessary if deps installed

# Recommended:
def load_cbor_entries(capture_file: Path) -> list[dict[str, Any]]:
    """Load entries from CBOR capture file.
    
    Note: cbor2 is a required dependency. ImportError here indicates
    a broken environment, not a missing optional dependency.
    """
    import cbor2  # Let ImportError propagate if missing (indicates broken env)
    # ... rest of function
```

#### For `tests/codex/integration/test_droid_codex_compatibility.py`:

```python
# Current (line 180):
@pytest.mark.skipif(cbor2 is None, reason="cbor2 not installed")  # ⚠️ Unnecessary

# Recommended:
# Remove skipif entirely since cbor2 is required, OR:
@pytest.mark.skipif(cbor2 is None, reason="cbor2 not installed (required dependency)")
# But this will never trigger if dependencies are properly installed
```

## Conclusion

- **cbor2 skips**: Defensive but unnecessary since it's a required dependency
- **gemini-cli skips**: ✅ Legitimate - optional external tool
- **Capture file skips**: ✅ Legitimate - require runtime-generated data

The main issue is that **cbor2 skip checks are defensive but unnecessary** since cbor2 is a required dependency. If cbor2 is missing, that indicates a broken environment, not a missing optional dependency.
