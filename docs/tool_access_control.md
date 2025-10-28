# Tool Access Control

## Overview

Tool Access Control provides fine-grained control over which tools LLMs can access and execute in the LLM Interactive Proxy. This feature operates at two levels to provide comprehensive protection:

1. **Request Filtering**: Removes disallowed tool definitions from requests before they reach the LLM, preventing wasted turns
2. **Response Blocking**: Blocks disallowed tool calls in LLM responses as a hard stop, even if the LLM attempts to use them

## Architecture

The tool access control system consists of three main components:

### 1. ToolAccessPolicyService

Centralized service that:
- Loads and validates access policies from configuration
- Compiles regex patterns for efficient matching
- Evaluates tool names against policies
- Selects the most specific matching policy for a given model/agent combination

### 2. Request Filtering (RequestProcessor)

Integrates with the request processing pipeline to:
- Filter tool definitions before sending requests to backends
- Handle `tool_choice` field when referenced tools are filtered
- Store policy metadata for observability
- Fail-open on errors to maintain availability

### 3. Tool Access Control Handler

Reactor handler that:
- Registers with the Tool Call Reactor at priority 90 (after dangerous-command handler)
- Evaluates tool calls in LLM responses
- Swallows disallowed tool calls and returns block messages
- Includes policy metadata in reaction results

## Configuration

### YAML Configuration

Tool access policies are configured in `config/tool_call_reactor_config.yaml`:

```yaml
session:
  tool_call_reactor:
    enabled: true
    access_policies:
      - name: policy_name
        model_pattern: "regex_pattern"
        agent_pattern: "regex_pattern"  # Optional
        allowed_patterns:
          - "tool_pattern_1"
          - "tool_pattern_2"
        blocked_patterns:
          - "tool_pattern_3"
          - "tool_pattern_4"
        default_policy: allow  # or deny
        block_message: "Custom message"
        priority: 100
```

### Configuration Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | string | Unique identifier for the policy |
| `model_pattern` | Yes | string | Regex pattern for matching model names |
| `agent_pattern` | No | string | Regex pattern for matching agent identifiers |
| `allowed_patterns` | No | list[string] | Regex patterns for allowed tools |
| `blocked_patterns` | No | list[string] | Regex patterns for blocked tools |
| `default_policy` | Yes | enum | Default behavior: "allow" or "deny" |
| `block_message` | No | string | Message returned when blocking a tool |
| `priority` | No | integer | Policy priority (default: 0) |

### CLI Arguments (Coming Soon)

```bash
python -m src.core.cli \
  --allowed-tools "read_.*,list_.*" \
  --blocked-tools "delete_.*,rm_.*" \
  --default-policy allow
```

### Environment Variables (Coming Soon)

```bash
export TOOL_ACCESS_ALLOWED_TOOLS="read_.*,list_.*"
export TOOL_ACCESS_BLOCKED_TOOLS="delete_.*,rm_.*"
export TOOL_ACCESS_DEFAULT_POLICY="allow"
```

## Policy Evaluation

### Pattern Matching

- All patterns are compiled as regex and matched case-insensitively
- Patterns support partial matching within tool names
- Use `.*` for wildcard matching (not just `*`)
- Escape special regex characters: `\.`, `\(`, `\)`, `\[`, `\]`, `\{`, `\}`, `\+`, `\*`, `\?`, `\^`, `\$`, `\|`

### Precedence Rules

1. **Allowed Overrides Blocked**: If a tool matches both allowed and blocked patterns, it is allowed
2. **Policy Priority**: Higher priority policies take precedence when multiple policies match
3. **Global Overrides Per-Model**: Global CLI/environment policies override configuration file policies (when implemented)
4. **Most Specific Match**: When multiple policies match, the most specific (highest priority) is used

### Default Policy Modes

#### Allow Mode (Blacklist)

```yaml
default_policy: allow
blocked_patterns:
  - "delete_.*"
  - "rm_.*"
```

- Tools are allowed by default
- Only explicitly blocked tools are denied
- Best for most use cases

#### Deny Mode (Whitelist)

```yaml
default_policy: deny
allowed_patterns:
  - "read_.*"
  - "list_.*"
```

- Tools are blocked by default
- Only explicitly allowed tools are permitted
- Best for high-security environments

## Common Use Cases

### 1. Prevent Destructive Operations

Block all file deletion and destructive operations:

```yaml
- name: prevent_destructive_ops
  model_pattern: ".*"
  default_policy: allow
  blocked_patterns:
    - "delete_.*"
    - "rm_.*"
    - "remove_.*"
    - "drop_.*"
    - "truncate_.*"
    - "destroy_.*"
  block_message: "Destructive operations are not allowed by policy."
  priority: 100
```

### 2. Read-Only Mode for Production

Allow only read operations in production environments:

```yaml
- name: production_readonly
  model_pattern: ".*"
  agent_pattern: "prod-.*"
  default_policy: deny
  allowed_patterns:
    - "read_.*"
    - "list_.*"
    - "get_.*"
    - "search_.*"
    - "find_.*"
    - "query_.*"
  block_message: "Only read operations are allowed in production."
  priority: 90
```

### 3. Model-Specific Restrictions

Restrict specific models to safe tools only:

```yaml
- name: restrict_experimental_model
  model_pattern: "experimental-.*"
  default_policy: deny
  allowed_patterns:
    - "read_file"
    - "list_directory"
    - "search_files"
  block_message: "Experimental models have limited tool access for safety."
  priority: 80
```

### 4. Agent-Based Access Control

Different tool access for different agent types:

```yaml
# Junior agents - limited access
- name: junior_agent_restrictions
  model_pattern: ".*"
  agent_pattern: "junior-.*"
  default_policy: allow
  blocked_patterns:
    - "execute_.*"
    - "deploy_.*"
    - "delete_.*"
    - "modify_production_.*"
  block_message: "Junior agents cannot execute, deploy, or delete resources."
  priority: 60

# Senior agents - full access
- name: senior_agent_full_access
  model_pattern: ".*"
  agent_pattern: "senior-.*"
  default_policy: allow
  blocked_patterns: []
  priority: 50
```

### 5. Database Protection

Prevent all database operations:

```yaml
- name: prevent_database_ops
  model_pattern: ".*"
  default_policy: allow
  blocked_patterns:
    - ".*sql.*"
    - ".*database.*"
    - ".*db_.*"
    - "drop_.*"
    - "truncate_.*"
    - "alter_.*"
  block_message: "Database operations are not allowed."
  priority: 90
```

### 6. Disable Tools for Specific Models

Completely disable tool calling for certain models:

```yaml
- name: no_tools_for_gpt4
  model_pattern: "openai:gpt-4-.*"
  default_policy: deny
  allowed_patterns: []
  blocked_patterns: []
  block_message: "Tool calling is disabled for this model."
  priority: 75
```

## Observability

### Logging

The proxy provides comprehensive logging for tool access control:

#### Request Filtering Logs

```
INFO: Filtered 2 tool definitions for model anthropic:claude-3-5-sonnet
DEBUG: Removed tools: delete_file, remove_directory
DEBUG: Policy 'block_dangerous_file_ops' matched for model 'anthropic:claude-3-5-sonnet'
```

#### Tool Call Blocking Logs

```
INFO: Blocked tool call 'delete_file' by policy 'block_dangerous_file_ops' in session abc123
DEBUG: Block reason: Tool matches blocked pattern 'delete_.*'
DEBUG: Block message: File deletion operations are not allowed by policy.
```

#### Policy Loading Logs

```
INFO: Loaded 5 tool access policies
DEBUG: Policy details: block_dangerous_file_ops, production_readonly, restrict_experimental_model, junior_agent_restrictions, prevent_database_ops
```

### Metadata

Policy evaluation metadata is stored in:

- **Request**: `request.extra_body["tool_access"]`
- **Response**: `response.metadata["tool_access"]`

Example metadata:

```json
{
  "policy_name": "block_dangerous_file_ops",
  "matched_pattern": "delete_.*",
  "action": "blocked",
  "filtered_tools": ["delete_file", "remove_directory"],
  "total_tools": 10,
  "filtered_count": 2
}
```

### Statistics

The Tool Call Reactor Service tracks:

- Number of filtered tool definitions per request
- Number of blocked tool calls per session
- Policy evaluation time (debug level)

## Performance

### Optimization Strategies

1. **Regex Compilation Caching**: All regex patterns are compiled once during initialization
2. **Policy Pre-Sorting**: Policies are sorted by priority during initialization
3. **Early Exit**: Policy selection stops at the first matching policy
4. **Minimal Overhead**: Typical policy evaluation adds <1ms per request

### Performance Targets

- Policy evaluation: <1ms per request
- Regex compilation: Once at startup
- Memory overhead: Minimal (compiled patterns cached)

### Scalability

- Recommended maximum: 20 policies per configuration
- Each policy can have unlimited patterns (within reason)
- Pattern complexity affects performance (prefer simple patterns)

## Troubleshooting

### Tool Definitions Not Being Filtered

**Symptoms**: Tool definitions appear in requests to the LLM even though they should be filtered

**Solutions**:
1. Verify `tool_call_reactor.enabled: true` in configuration
2. Check that your `model_pattern` matches the actual model name
   - Use `.*` to match all models
   - Check logs for the exact model name being used
3. Review startup logs for policy loading errors
4. Verify regex patterns are correct (test with a regex validator)
5. Check policy priority - ensure your policy has higher priority than conflicting policies

### Tool Calls Not Being Blocked

**Symptoms**: LLM successfully calls tools that should be blocked

**Solutions**:
1. Ensure the Tool Access Control Handler is registered (check startup logs)
2. Verify your patterns match the tool names exactly
   - Patterns are case-insensitive
   - Use `.*` for wildcard matching
3. Check policy priority - higher priority policies override lower ones
4. Review logs for policy evaluation results
5. Verify `tool_call_reactor.enabled: true`

### Regex Pattern Errors

**Symptoms**: Configuration fails to load or patterns don't match expected tools

**Solutions**:
1. Test regex patterns with a regex validator (e.g., regex101.com)
2. Escape special characters: `\.`, `\(`, `\)`, `\[`, `\]`, `\{`, `\}`, `\+`, `\*`, `\?`, `\^`, `\$`, `\|`
3. Use `.*` for wildcard matching, not just `*`
4. Check startup logs for specific pattern compilation errors
5. Use simple patterns when possible (e.g., `delete_file` instead of `delete_.*_file.*`)

### Performance Issues

**Symptoms**: Slow request processing or high CPU usage

**Solutions**:
1. Limit the number of policies (recommend <20)
2. Use specific patterns instead of complex regex
3. Avoid excessive use of `.*` wildcards
4. Monitor policy evaluation time in debug logs
5. Consider caching policy lookups by (model_name, agent) key

### Policy Not Matching

**Symptoms**: Policy doesn't apply to expected models or agents

**Solutions**:
1. Check model name format - use `backend:model` or just `model`
2. Verify agent pattern matches the actual agent identifier
3. Test patterns with actual model/agent names from logs
4. Use `.*` to match all models/agents for testing
5. Check policy priority - ensure it's higher than conflicting policies

## Best Practices

### 1. Start Simple

Begin with blacklist mode (allow by default) and specific blocked patterns:

```yaml
- name: basic_safety
  model_pattern: ".*"
  default_policy: allow
  blocked_patterns:
    - "delete_file"
    - "remove_directory"
  priority: 100
```

### 2. Use Specific Patterns

Prefer specific tool names over broad wildcards:

```yaml
# Good - specific
blocked_patterns:
  - "delete_file"
  - "remove_directory"
  - "drop_table"

# Less ideal - too broad
blocked_patterns:
  - ".*delete.*"
  - ".*remove.*"
```

### 3. Test in Development

Always test new policies in a development environment before production:

1. Add policy to development configuration
2. Test with various tool calls
3. Review logs for unexpected filtering/blocking
4. Adjust patterns as needed
5. Deploy to production

### 4. Monitor and Refine

Regularly review logs to refine policies:

1. Check filtered tools and blocked calls
2. Identify false positives (tools incorrectly blocked)
3. Identify false negatives (tools that should be blocked)
4. Adjust patterns and priorities
5. Document changes

### 5. Document Policies

Add comments explaining each policy's purpose:

```yaml
access_policies:
  # Prevent accidental deletion of critical files
  # Added: 2025-01-15
  # Owner: Security Team
  - name: prevent_critical_file_deletion
    model_pattern: ".*"
    default_policy: allow
    blocked_patterns:
      - "delete_file"
      - "remove_directory"
    block_message: "Critical file operations require manual approval."
    priority: 100
```

### 6. Layer Security

Combine tool access control with other safety features:

- Dangerous-command prevention (blocks harmful shell commands)
- Loop detection (prevents infinite loops)
- Rate limiting (prevents abuse)
- Session management (tracks usage patterns)

### 7. Use Priority Effectively

Assign priorities based on specificity and importance:

- 100+: Critical security policies (apply to all models)
- 75-99: Model-specific restrictions
- 50-74: Agent-specific restrictions
- 25-49: Feature-specific policies
- 0-24: Default/fallback policies

### 8. Fail-Open for Availability

The system is designed to fail-open (allow tools) on errors to maintain availability. For critical security requirements:

1. Test policies thoroughly
2. Monitor error logs
3. Consider additional security layers
4. Use explicit deny policies for critical tools

## Examples

### Complete Configuration Example

```yaml
session:
  tool_call_reactor:
    enabled: true
    access_policies:
      # Critical security - block destructive operations
      - name: prevent_destructive_ops
        model_pattern: ".*"
        default_policy: allow
        blocked_patterns:
          - "delete_.*"
          - "rm_.*"
          - "remove_.*"
          - "drop_.*"
          - "truncate_.*"
        block_message: "Destructive operations are not allowed."
        priority: 100
      
      # Production environment - read-only
      - name: production_readonly
        model_pattern: ".*"
        agent_pattern: "prod-.*"
        default_policy: deny
        allowed_patterns:
          - "read_.*"
          - "list_.*"
          - "get_.*"
          - "search_.*"
        block_message: "Only read operations are allowed in production."
        priority: 90
      
      # Experimental models - minimal access
      - name: experimental_limited
        model_pattern: "experimental-.*"
        default_policy: deny
        allowed_patterns:
          - "read_file"
          - "list_directory"
        block_message: "Experimental models have limited tool access."
        priority: 80
      
      # Junior agents - restricted access
      - name: junior_restrictions
        model_pattern: ".*"
        agent_pattern: "junior-.*"
        default_policy: allow
        blocked_patterns:
          - "execute_.*"
          - "deploy_.*"
          - "delete_.*"
        block_message: "Junior agents have restricted tool access."
        priority: 60
```

### Testing Policy Configuration

```python
# Test script to verify policy configuration
import yaml
import re

def test_policy(policy, tool_name):
    """Test if a tool is allowed by a policy."""
    # Compile patterns
    allowed = [re.compile(p, re.IGNORECASE) for p in policy.get('allowed_patterns', [])]
    blocked = [re.compile(p, re.IGNORECASE) for p in policy.get('blocked_patterns', [])]
    
    # Check allowed patterns
    is_allowed = any(p.search(tool_name) for p in allowed)
    
    # Check blocked patterns
    is_blocked = any(p.search(tool_name) for p in blocked)
    
    # Apply precedence: allowed overrides blocked
    if is_allowed:
        return True
    if is_blocked:
        return False
    
    # Apply default policy
    return policy['default_policy'] == 'allow'

# Load configuration
with open('config/tool_call_reactor_config.yaml') as f:
    config = yaml.safe_load(f)

policies = config['session']['tool_call_reactor']['access_policies']

# Test tools
test_tools = [
    'read_file',
    'delete_file',
    'list_directory',
    'execute_command',
    'search_files'
]

for policy in policies:
    print(f"\nPolicy: {policy['name']}")
    for tool in test_tools:
        allowed = test_policy(policy, tool)
        print(f"  {tool}: {'✓ Allowed' if allowed else '✗ Blocked'}")
```

## Security Considerations

### Defense in Depth

Tool access control is one layer of security. Combine with:

1. **Authentication**: Require API keys for proxy access
2. **Authorization**: Use agent patterns for role-based access
3. **Dangerous Command Prevention**: Block harmful shell commands
4. **Loop Detection**: Prevent infinite loops
5. **Rate Limiting**: Prevent abuse
6. **Audit Logging**: Track all tool usage

### Bypass Prevention

The system prevents bypasses by:

1. **Proxy-Level Enforcement**: Cannot be bypassed by client
2. **Two-Layer Protection**: Filters requests AND blocks responses
3. **Pattern Validation**: Validates regex patterns at startup
4. **Metadata Sanitization**: Sanitizes policy metadata in responses

### Audit Trail

Maintain comprehensive audit logs:

1. Log all blocked tool calls with session ID, tool name, and policy
2. Include policy metadata in responses for debugging
3. Track policy effectiveness metrics
4. Export audit logs for compliance

## Future Enhancements

Potential future features:

1. **Dynamic Policy Updates**: Runtime policy updates without restart
2. **Policy Templates**: Pre-defined policy sets for common scenarios
3. **Tool Usage Analytics**: Dashboard showing tool usage patterns
4. **Per-User Policies**: User-level restrictions
5. **Policy Testing Mode**: Dry-run mode that logs but doesn't block
6. **Policy Inheritance**: Support policy hierarchies
7. **Rate Limiting**: Per-tool rate limiting
8. **Conditional Policies**: Time-based or context-based activation
9. **CLI Parameter Support**: Global policy overrides via CLI
10. **Environment Variable Support**: Policy configuration via environment

## References

- [Design Document](../.kiro/specs/tool-access-control/design.md)
- [Requirements Document](../.kiro/specs/tool-access-control/requirements.md)
- [Implementation Tasks](../.kiro/specs/tool-access-control/tasks.md)
- [Tool Call Reactor Documentation](tool_call_reactor.md) (if exists)
