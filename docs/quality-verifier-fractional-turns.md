# Quality Verifier Fractional Turn Counting

## Problem

The Quality Verifier's turn counting mechanism had a critical bug: tool followup requests (requests with `tool` role messages after the last user message) caused the turn counter to **not increment at all**. This meant that in typical coding sessions with frequent tool use, the Quality Verifier would never reach its frequency threshold (e.g., turn 10, turn 20, etc.) and would essentially never run.

### Original Buggy Behavior

```python
# In _prepare_quality_verifier_extensions_for_backend_call
if skip:  # is_tool_followup or replacement_active
    context.extensions.pop("quality_verifier_eligible_turn_count", None)
    if logger.isEnabledFor(logging.DEBUG):
        skip_reason = (
            "tool_followup" if is_tool_followup else "replacement_active"
        )
        # ... log skip reason ...
    return  # <-- BUG: This prevented counter increment
# ... later code to increment counter was never reached for tool followups ...
```

This caused the `eligible_turn` count to only increment for regular user messages, which are rare in coding sessions where most interactions involve tool calls/results.

## Solution: Fractional Turn Counting

Tool followup requests now count as **fractional turns** (default: `0.1`) instead of being completely excluded from turn counting. This ensures that the Quality Verifier will eventually trigger even in tool-heavy workloads.

### Configuration

A new configuration parameter controls the fractional weight:

```yaml
session:
  quality_verifier_tool_followup_weight: 0.1  # Default: 0.1
```

- **Range**: `0.0` to `1.0`
- **Default**: `0.1` (10 tool followups = 1 full turn)
- **Special case**: Set to `0.0` to completely exclude tool followups from turn counting (not recommended)

### Updated Behavior

1. **Regular user turn**: `turn_count += 1.0`
2. **Tool followup request**: `turn_count += 0.1` (or configured weight)
3. **Replacement active**: `turn_count` unchanged (existing behavior)

The turn counter is now a `float` instead of an `int`, allowing gradual accumulation across tool-heavy interactions.

### Example

With the default weight of `0.1`:

- User message → turn count: `1.0`
- Tool result → turn count: `1.1`
- Tool result → turn count: `1.2`
- ...
- Tool result → turn count: `1.9`
- Tool result → turn count: `2.0` ← **Quality Verifier triggers at frequency=10 when count reaches 10.0**

### Technical Implementation

1. **Config Model** (`src/core/config/models/session.py`):
   - Added `quality_verifier_tool_followup_weight: float = 0.1`
   - Added validator to clamp value between `0.0` and `1.0`

2. **YAML Schema** (`config/schemas/app_config.schema.yaml`):
   - Added `quality_verifier_tool_followup_weight` field with type `number`, min `0.0`, max `1.0`

3. **Request Processor** (`src/core/services/request_processor_service.py`):
   - Changed turn counter from `int` to `float` throughout
   - Tool followups now increment by `quality_verifier_tool_followup_weight` instead of being skipped
   - Replacement-active turns still don't increment (unchanged behavior)
   - Updated logging to show fractional turn counts

4. **Tests** (`tests/unit/core/services/test_quality_verifier_fractional_turns.py`):
   - Unit tests for fractional turn storage and accumulation
   - Regression tests to prevent re-introduction of the bug

### Triggering Logic

The Quality Verifier still triggers based on the **integer floor** of the turn count:

```python
current_turn_floor = int(current_eligible_turn_count)
should_run = (current_turn_floor > 0) and (current_turn_floor % frequency) == 0
```

This means that with frequency=10:
- Turn count `9.8` → no trigger
- Turn count `10.0` → **trigger!**
- Turn count `10.1` → no trigger
- Turn count `19.9` → no trigger
- Turn count `20.0` → **trigger!**

## Benefits

1. **Quality Verifier actually runs**: No longer blocked by tool-heavy workloads
2. **Configurable**: Weight can be tuned based on observed behavior
3. **Backward compatible**: Default weight of `0.1` is conservative and won't cause excessive Quality Verifier calls
4. **Graceful degradation**: In tool-heavy sessions, Quality Verifier still triggers eventually (after ~100 tool calls with default weight)

## Tuning Recommendations

- **Default (`0.1`)**: Good balance for most coding sessions
- **Higher (`0.2-0.3`)**: For projects with very frequent tool use where you want more frequent Quality Verifier checks
- **Lower (`0.05`)**: For projects where tool calls are expected to be very long sequences
- **Zero (`0.0`)**: Not recommended; reverts to buggy behavior where tool followups don't count

## Migration Notes

Existing sessions with integer turn counts will automatically upgrade to float:
- Stored count `5` → loaded as `5.0`
- Next tool followup → `5.1`
- Seamless transition, no data migration required
