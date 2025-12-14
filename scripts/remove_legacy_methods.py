
import re
from pathlib import Path

file_path = Path("src/core/services/backend_service.py")
content = file_path.read_text(encoding="utf-8")

# List of methods to remove (including docstrings and body)
methods_to_remove = [
    "_apply_model_aliases",
    "_stream_as_sse_bytes",
    "_is_valid_completion_token",
    "_wrap_stream_for_usage",
    "_normalize_provider_exception",
    "_resolve_stream_session_id", # This one was not in the original list but seems to be a helper. 
                                  # Wait, let's check if it's used by other extracted services or if it should be kept.
                                  # It's used in call_completion. It wasn't extracted to a service in the plan?
                                  # Let's check the plan.
                                  # Plan didn't explicitly mention _resolve_stream_session_id extraction.
                                  # Let's double check if it is extracted. 
                                  # It's NOT in the list of extracted services. So we should KEEP it.
                                  # Re-checking the list of methods to remove:
                                  # _stream_as_sse_bytes
                                  # _is_valid_completion_token
                                  # _wrap_stream_for_usage
                                  # _apply_model_aliases
                                  # _apply_uri_parameters
                                  # _apply_reasoning_config
                                  # _apply_planning_phase_if_needed
                                  # _update_planning_phase_counters
                                  # _count_file_writes_in_response
                                  # _get_or_create_backend
                                  # _shutdown_backend
                                  # _discard_backend
                                  # _normalize_provider_exception
                                  # _restore_planning_phase_route
]

# We need to be careful with _resolve_stream_session_id. It seems it wasn't extracted.
# Also _execute_complex_failover, _attempt_failover_plan, _apply_failure_strategy, _filter_unhealthy_backends
# These seem to be remaining in BackendService as per the plan (or lack of extraction plan).

# Let's remove the ones that are definitely wrappers now.

def remove_method(content, method_name):
    # This regex tries to find the method definition and its body.
    # It assumes standard python indentation (4 spaces).
    # It stops when it hits another method definition (non-indented async? def) or class end.
    
    # Python methods start with '    def ' or '    async def ' inside a class
    # We look for the specific method name
    pattern = r"(    (?:async )?def " + method_name + r"\(.*?\):\n(?:        .*?\n)+)"
    
    # We need to handle decorators if any (like @staticmethod)
    # The pattern above matches the def line and subsequent indented lines.
    # It's a bit risky with regex.
    
    # Better approach: find start index, find end index based on indentation.
    
    search_str = f"def {method_name}("
    start_idx = content.find(search_str)
    if start_idx == -1:
        print(f"Method {method_name} not found")
        return content
    
    # Backtrack to find decorators or 'async'
    line_start = content.rfind('\n', 0, start_idx) + 1
    
    # Check for decorators above
    # scan backwards from line_start for lines starting with '    @'
    chunk_start = line_start
    while True:
        prev_line_end = chunk_start - 1
        if prev_line_end < 0:
            break
        prev_line_start = content.rfind('\n', 0, prev_line_end) + 1
        line = content[prev_line_start:prev_line_end+1]
        if line.strip().startswith('@'):
            chunk_start = prev_line_start
        else:
            break
            
    # Now find the end of the method
    # It ends when we encounter a line with same indentation as chunk_start (usually 4 spaces)
    # or less indentation, that is NOT empty.
    
    # We assume standard 4 space indentation for class methods
    indentation = "    "
    
    curr_idx = content.find(':', start_idx) + 1
    if curr_idx == 0:
        return content # Should not happen
        
    length = len(content)
    end_idx = length
    
    # Scan line by line
    next_line_start = content.find('\n', curr_idx) + 1
    while next_line_start < length:
        line_end = content.find('\n', next_line_start)
        if line_end == -1:
            line_end = length
            
        line = content[next_line_start:line_end]
        
        # Check if line is empty or just whitespace
        if not line.strip():
            next_line_start = line_end + 1
            continue
            
        # Check indentation
        if not line.startswith(indentation + " "): # At least 5 spaces (body indentation)
            # If it starts with 4 spaces but it's a dedent (e.g. next method), we stop
            # But wait, next method also starts with 4 spaces.
            # So if it starts with exactly 4 spaces (or less), it's the next block
            if not line.startswith(indentation + "    "): # Less than 8 spaces indentation
                 # It could be closing parenthesis of def if it was multi-line?
                 # No, we assume we passed the colon.
                 # Actually, if we are inside the body, valid lines have 8 spaces.
                 # If we see 4 spaces, it's a new method or property in the class.
                 # If we see 0 spaces, it's end of class.
                 end_idx = next_line_start
                 break
        
        next_line_start = line_end + 1
        
    # Remove the chunk
    # Include the preceding newline if possible to avoid leaving empty lines
    return content[:chunk_start] + content[end_idx:]

# Specific list based on the user request
methods = [
    "_apply_model_aliases",
    "_stream_as_sse_bytes",
    "_is_valid_completion_token",
    "_wrap_stream_for_usage",
    "_normalize_provider_exception",
    "_apply_uri_parameters",
    "_apply_reasoning_config",
    "_apply_planning_phase_if_needed",
    "_update_planning_phase_counters",
    "_count_file_writes_in_response",
    "_get_or_create_backend",
    "_shutdown_backend",
    "_discard_backend",
    "_restore_planning_phase_route",
    "_enforce_per_session_backend_limit" # Also this one was wrapper
]

# Before removing, we must verify that these methods are NOT called internally by other methods in BackendService.
# I will check for internal calls first.

internal_calls = []
for m in methods:
    # Check if "self.m(" exists in content (excluding the definition itself)
    # We simple check count. Definition is one. Calls are others.
    # Note: definition might be "def m(" or "async def m(".
    # Call is "self.m(".
    
    call_pattern = f"self.{m}("
    if call_pattern in content:
        internal_calls.append(m)

if internal_calls:
    print("Warning: The following legacy methods are still called internally:")
    for m in internal_calls:
        print(f"  {m}")
    print("We must replace these calls with direct service calls first.")
else:
    print("No internal calls to legacy methods found. Proceeding with removal.")
    for m in methods:
        content = remove_method(content, m)
        print(f"Removed {m}")
    
    file_path.write_text(content, encoding="utf-8")
