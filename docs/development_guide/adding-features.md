# Adding Features

This guide covers how to add new features to the LLM Interactive Proxy, including design considerations, implementation patterns, and best practices.

## Feature Development Process

### 1. Planning

Before writing code:

1. **Define the feature**: What problem does it solve?
2. **Design the interface**: How will users interact with it?
3. **Consider architecture**: Where does it fit in the system?
4. **Plan testing**: How will you test it?
5. **Document requirements**: Write clear requirements

### 2. Design

Create a design document covering:

- **Overview**: What the feature does
- **Architecture**: How it integrates with existing system
- **Components**: What new components are needed
- **Data Models**: What data structures are required
- **Configuration**: What configuration options are needed
- **Testing Strategy**: How to test the feature

### 3. Implementation

Follow Test-Driven Development:

1. Write tests first
2. Implement minimal code to pass tests
3. Refactor while keeping tests green
4. Add integration tests
5. Update documentation

## Feature Types

### Request/Response Middleware

Middleware processes requests before they reach backends or responses before they reach clients.

**Use Cases**:

- Content filtering
- Request augmentation
- Response transformation
- Logging and monitoring

**Implementation**:

1. **Create middleware class**:

   ```python
   # src/core/middleware/your_middleware.py
   
   from src.core.interfaces.middleware_interface import IMiddleware
   from src.core.models.request import Request
   from src.core.models.response import Response
   
   class YourMiddleware(IMiddleware):
       """Your middleware description."""
       
       async def process_request(self, request: Request) -> Request:
           """Process request before backend."""
           # Your logic here
           return request
       
       async def process_response(self, response: Response) -> Response:
           """Process response before client."""
           # Your logic here
           return response
   ```

2. **Register middleware**:

   ```python
   # src/core/app/middleware_config.py
   
   from src.core.middleware.your_middleware import YourMiddleware
   
   def register_middleware(app):
       app.add_middleware(YourMiddleware)
   ```

3. **Add configuration**:

   ```python
   # src/core/config/app_config.py
   
   class YourFeatureConfig(DomainModel):
       enabled: bool = True
       option1: str = "default"
   ```

4. **Write tests**:

   ```python
   # tests/unit/middleware/test_your_middleware.py
   
   @pytest.mark.asyncio
   async def test_your_middleware_processes_request():
       middleware = YourMiddleware()
       request = Request(...)
       
       result = await middleware.process_request(request)
       
       assert result.modified_field == expected_value
   ```

### Command Handlers

Commands allow users to control the proxy through in-chat commands (e.g., `!/backend(...)`).

**Use Cases**:

- Switching backends
- Changing models
- Adjusting parameters
- Triggering actions

**Implementation**:

1. **Create command handler**:

   ```python
   # src/core/commands/your_command.py
   
   from src.core.interfaces.command_interface import ICommandHandler
   from src.core.models.command import CommandContext, CommandResult
   
   class YourCommandHandler(ICommandHandler):
       """Your command description."""
       
       @property
       def name(self) -> str:
           return "your_command"
       
       @property
       def pattern(self) -> str:
           return r"!/your_command\((.*?)\)"
       
       async def execute(self, context: CommandContext) -> CommandResult:
           """Execute the command."""
           # Parse arguments
           args = self.parse_args(context.match.group(1))
           
           # Execute logic
           result = self.do_something(args)
           
           return CommandResult(
               success=True,
               message=f"Command executed: {result}"
           )
   ```

2. **Register command**:

   ```python
   # src/core/di/services.py
   
   from src.core.commands.your_command import YourCommandHandler
   
   def register_commands(registry):
       registry.register(YourCommandHandler())
   ```

3. **Write tests**:

   ```python
   # tests/unit/commands/test_your_command.py
   
   @pytest.mark.asyncio
   async def test_your_command_executes():
       handler = YourCommandHandler()
       context = CommandContext(
           match=re.match(handler.pattern, "!/your_command(arg)")
       )
       
       result = await handler.execute(context)
       
       assert result.success
       assert "Command executed" in result.message
   ```

### Services

Services implement business logic and orchestrate domain objects.

**Use Cases**:

- Complex business logic
- Multi-step operations
- State management
- External integrations

**Implementation**:

1. **Define interface**:

   ```python
   # src/core/interfaces/your_service_interface.py
   
   from abc import ABC, abstractmethod
   
   class IYourService(ABC):
       """Your service interface."""
       
       @abstractmethod
       async def do_something(self, param: str) -> Result:
           """Do something."""
           pass
   ```

2. **Implement service**:

   ```python
   # src/core/services/your_service.py
   
   from src.core.interfaces.your_service_interface import IYourService
   
   class YourService(IYourService):
       """Your service implementation."""
       
       def __init__(self, dependency: IDependency):
           self.dependency = dependency
       
       async def do_something(self, param: str) -> Result:
           """Do something."""
           # Your logic here
           return Result(...)
   ```

3. **Register with DI**:

   ```python
   # src/core/di/services.py
   
   from src.core.services.your_service import YourService
   from src.core.interfaces.your_service_interface import IYourService
   
   container.register(IYourService, YourService)
   ```

4. **Write tests**:

   ```python
   # tests/unit/services/test_your_service.py
   
   @pytest.mark.asyncio
   async def test_your_service_does_something():
       mock_dependency = Mock()
       service = YourService(mock_dependency)
       
       result = await service.do_something("param")
       
       assert result.success
   ```

### Tool Call Handlers

Tool call handlers react to tool calls from LLMs, enabling monitoring and steering.

**Use Cases**:

- Tool call monitoring
- Tool call steering
- Safety enforcement
- Usage analytics

**Implementation**:

1. **Create handler**:

   ```python
   # src/core/services/tool_call_handlers/your_handler.py
   
   from src.core.interfaces.tool_call_reactor_interface import (
       IToolCallHandler,
       ToolCallContext,
       ToolCallReactionResult
   )
   
   class YourToolCallHandler(IToolCallHandler):
       """Your tool call handler."""
       
       @property
       def name(self) -> str:
           return "your_handler"
       
       @property
       def priority(self) -> int:
           return 100
       
       async def can_handle(self, context: ToolCallContext) -> bool:
           """Check if this handler should process the tool call."""
           return context.tool_name == "target_tool"
       
       async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
           """Process the tool call."""
           if should_steer:
               return ToolCallReactionResult(
                   should_swallow=True,
                   replacement_response="Steering message",
                   metadata={"handler": self.name}
               )
           else:
               return ToolCallReactionResult(
                   should_swallow=False,
                   metadata={"handler": self.name}
               )
   ```

2. **Register handler**:

   ```python
   # src/core/di/services.py
   
   from src.core.services.tool_call_handlers.your_handler import YourToolCallHandler
   
   def register_tool_call_handlers(reactor):
       handler = YourToolCallHandler()
       await reactor.register_handler(handler)
   ```

3. **Add configuration**:

   ```python
   # src/core/config/app_config.py
   
   class ToolCallReactorConfig(DomainModel):
       your_handler_enabled: bool = True
       your_handler_rate_limit_seconds: int = 60
   ```

4. **Write tests**:

   ```python
   # tests/unit/tool_call_handlers/test_your_handler.py
   
   @pytest.mark.asyncio
   async def test_your_handler_steers_tool_call():
       handler = YourToolCallHandler()
       context = ToolCallContext(tool_name="target_tool")
       
       result = await handler.handle(context)
       
       assert result.should_swallow
       assert "Steering message" in result.replacement_response
   ```

## Configuration

### Adding Configuration Options

1. **Define configuration model**:

   ```python
   # src/core/config/app_config.py
   
   class YourFeatureConfig(DomainModel):
       """Configuration for your feature."""
       enabled: bool = True
       option1: str = "default"
       option2: int = 100
   ```

2. **Add to main config**:

   ```python
   # src/core/config/app_config.py
   
   class AppConfig(DomainModel):
       your_feature: YourFeatureConfig = YourFeatureConfig()
   ```

3. **Add CLI arguments**:

   ```python
   # src/core/cli.py
   
   parser.add_argument(
       "--enable-your-feature",
       action="store_true",
       help="Enable your feature"
   )
   parser.add_argument(
       "--your-feature-option1",
       type=str,
       default="default",
       help="Your feature option 1"
   )
   ```

4. **Add environment variables**:

   ```bash
   # config/sample.env
   
   YOUR_FEATURE_ENABLED=true
   YOUR_FEATURE_OPTION1=value
   YOUR_FEATURE_OPTION2=100
   ```

5. **Add YAML configuration**:

   ```yaml
   # config/config.example.yaml
   
   your_feature:
     enabled: true
     option1: value
     option2: 100
   ```

### Configuration Precedence

Configuration is loaded in this order (later overrides earlier):

1. Default values in code
2. YAML configuration file
3. Environment variables
4. CLI arguments

## Testing Features

### Unit Tests

Test individual components in isolation:

```python
# tests/unit/test_your_feature.py

def test_your_feature_does_something():
    """Test that your feature does something."""
    feature = YourFeature(config)
    
    result = feature.do_something()
    
    assert result == expected
```

### Integration Tests

Test how components work together:

```python
# tests/integration/test_your_feature_integration.py

@pytest.mark.asyncio
async def test_your_feature_integrates_with_backend():
    """Test that your feature integrates with backend."""
    feature = YourFeature(config)
    backend = MockBackend()
    
    result = await feature.process_with_backend(backend)
    
    assert result.success
```

### End-to-End Tests

Test complete request flows:

```python
# tests/behavior/test_your_feature_e2e.py

@pytest.mark.asyncio
async def test_your_feature_end_to_end():
    """Test your feature end-to-end."""
    async with TestClient(app) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [...]}
        )
    
    assert response.status_code == 200
    assert "expected_field" in response.json()
```

## Documentation

### User Documentation

Create user-facing documentation in `docs/user_guide/features/`:

```markdown
# Your Feature

Brief description of what your feature does.

## Overview

Detailed description of the feature and its benefits.

## Configuration

### CLI Arguments

```bash
--enable-your-feature
--your-feature-option1 VALUE
```

### Environment Variables

```bash
export YOUR_FEATURE_ENABLED=true
export YOUR_FEATURE_OPTION1=value
```

### YAML Configuration

```yaml
your_feature:
  enabled: true
  option1: value
```

## Usage Examples

Practical examples showing how to use the feature.

## Use Cases

Common scenarios where this feature is valuable.

## Troubleshooting

Common issues and solutions.
```

### Developer Documentation

Update developer documentation:

- **Architecture**: Update [architecture.md](architecture.md) if adding new components
- **Code Organization**: Update [code-organization.md](code-organization.md) if adding new modules
- **This Guide**: Add your feature type if it's a new pattern

## Best Practices

### Design Principles

1. **Single Responsibility**: Each component should have one responsibility
2. **Interface-Driven**: Define interfaces before implementations
3. **Dependency Injection**: Use DI for dependencies
4. **Immutable Models**: Use immutable Pydantic models
5. **Error Handling**: Use specific exceptions with clear messages

### Code Quality

1. **Type Hints**: Use type hints for all functions
2. **Docstrings**: Document all public functions/classes
3. **Tests**: Write tests before implementation
4. **Coverage**: Aim for 80%+ test coverage
5. **Linting**: Pass ruff and black checks

### Performance

1. **Async/Await**: Use async for I/O operations
2. **Connection Pooling**: Reuse HTTP connections
3. **Caching**: Cache expensive computations
4. **Lazy Loading**: Defer initialization when possible
5. **Profiling**: Profile performance-critical code

### Security

1. **Input Validation**: Validate all user input
2. **API Key Redaction**: Never log API keys
3. **Error Messages**: Don't leak sensitive information
4. **Rate Limiting**: Implement rate limiting for expensive operations
5. **Access Control**: Enforce proper access controls

## Common Patterns

### Feature Flags

Use configuration to enable/disable features:

```python
class YourFeatureConfig(DomainModel):
    enabled: bool = True

# In your code
if config.your_feature.enabled:
    # Feature logic
    pass
```

### Rate Limiting

Implement per-session rate limiting:

```python
class YourFeature:
    def __init__(self):
        self.last_execution: Dict[str, float] = {}
        self.rate_limit_seconds = 60
    
    async def execute(self, session_id: str):
        now = time.time()
        last = self.last_execution.get(session_id, 0)
        
        if now - last < self.rate_limit_seconds:
            return  # Rate limited
        
        self.last_execution[session_id] = now
        # Execute logic
```

### Graceful Degradation

Handle failures gracefully:

```python
async def your_feature(request):
    try:
        result = await expensive_operation(request)
        return result
    except Exception as e:
        logger.warning(f"Feature failed: {e}")
        return fallback_result(request)
```

## Examples

### Example: Adding Content Filter

1. **Define interface**:

   ```python
   class IContentFilter(ABC):
       @abstractmethod
       async def filter(self, content: str) -> str:
           pass
   ```

2. **Implement filter**:

   ```python
   class ProfanityFilter(IContentFilter):
       async def filter(self, content: str) -> str:
           # Filter logic
           return filtered_content
   ```

3. **Add middleware**:

   ```python
   class ContentFilterMiddleware(IMiddleware):
       def __init__(self, filter: IContentFilter):
           self.filter = filter
       
       async def process_response(self, response):
           response.content = await self.filter.filter(response.content)
           return response
   ```

4. **Register with DI**:

   ```python
   container.register(IContentFilter, ProfanityFilter)
   ```

5. **Write tests**:

   ```python
   @pytest.mark.asyncio
   async def test_profanity_filter():
       filter = ProfanityFilter()
       result = await filter.filter("bad word")
       assert "bad word" not in result
   ```

## Related Documentation

- **Architecture**: See [architecture.md](architecture.md) for system architecture
- **Code Organization**: See [code-organization.md](code-organization.md) for project structure
- **Building**: See [building.md](building.md) for build instructions
- **Testing**: See [testing.md](testing.md) for testing guidelines
- **Contributing**: See [contributing.md](contributing.md) for contribution workflow
- **Adding Backends**: See [adding-backends.md](adding-backends.md) for backend development
- **Coding Standards**: See [AGENTS.md](../../AGENTS.md) for detailed coding standards
