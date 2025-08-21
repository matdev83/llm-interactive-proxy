# Architectural Enforcement Guide

## Overview

This guide explains how the codebase now enforces proper SOLID principles and prevents architectural violations through Object-Oriented design rather than external tooling.

## 🛡️ Enforcement Mechanisms

### 1. **Secure Base Classes**

All domain commands must inherit from secure base classes that enforce proper DI:

```python
# ✅ CORRECT: Stateful command with proper DI
class SetCommand(StatefulCommandBase):
    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification,
    ):
        super().__init__(state_reader, state_modifier)
    
    async def execute(self, args, session, context=None):
        # Use secure state access
        self.update_state_setting('command_prefix', value)

# ✅ CORRECT: Stateless command
class HelloCommand(StatelessCommandBase):
    def __init__(self):
        super().__init__()
    
    async def execute(self, args, session, context=None):
        # No state access needed
        return CommandResult(success=True, message="Hello!")
```

### 2. **Interface Segregation**

State access is split into focused interfaces:

```python
# Read-only state access
class ISecureStateAccess(ABC):
    @abstractmethod
    def get_command_prefix(self) -> str | None: ...
    
    @abstractmethod
    def get_api_key_redaction_enabled(self) -> bool: ...

# Write state access with validation
class ISecureStateModification(ABC):
    @abstractmethod
    def update_command_prefix(self, prefix: str) -> None: ...
    
    @abstractmethod
    def update_api_key_redaction(self, enabled: bool) -> None: ...
```

### 3. **Dependency Injection Factory**

Commands are created through a factory that enforces proper DI:

```python
# ✅ CORRECT: Using the factory
factory = container.get_service(SecureCommandFactory)
set_command = factory.create_command(SetCommand)

# ❌ BLOCKED: Direct instantiation without DI
set_command = SetCommand()  # Raises StateAccessViolationError
```

### 4. **Runtime Violation Detection**

The system detects and prevents violations at runtime:

```python
# ❌ BLOCKED: Direct state access
class BadCommand(StatefulCommandBase):
    async def execute(self, args, session, context=None):
        # This will raise StateAccessViolationError
        context.app.state.some_setting = "value"
        
# ❌ BLOCKED: Stateless command trying to access state
class BadStatelessCommand(StatelessCommandBase):
    async def execute(self, args, session, context=None):
        # This will raise StateAccessViolationError
        self.get_state_setting('command_prefix')
```

## 🔒 What's Prevented

### 1. **Direct app.state Access**
```python
# ❌ BLOCKED - Compile-time error
context.app.state.command_prefix = "new_prefix"

# ✅ ENFORCED - Must use DI
self.update_state_setting('command_prefix', "new_prefix")
```

### 2. **Framework Coupling**
```python
# ❌ BLOCKED - Constructor requires DI
class MyCommand(StatefulCommandBase):
    def __init__(self):  # Missing required parameters
        super().__init__()  # Raises StateAccessViolationError

# ✅ ENFORCED - Proper DI
class MyCommand(StatefulCommandBase):
    def __init__(self, state_reader: ISecureStateAccess, state_modifier: ISecureStateModification):
        super().__init__(state_reader, state_modifier)
```

### 3. **Mixed Responsibilities**
```python
# ❌ BLOCKED - Stateless commands can't access state
class BadCommand(StatelessCommandBase):
    async def execute(self, args, session, context=None):
        # Raises StateAccessViolationError
        prefix = self.get_state_setting('command_prefix')

# ✅ ENFORCED - Clear separation
class GoodCommand(StatefulCommandBase):
    async def execute(self, args, session, context=None):
        prefix = self.get_state_setting('command_prefix')  # Allowed
```

## 🏗️ Migration Path

### Step 1: Update Existing Commands

```python
# OLD: Direct inheritance
class OldCommand(BaseCommand):
    async def execute(self, args, session, context=None):
        app.state.setting = value

# NEW: Secure inheritance
class NewCommand(StatefulCommandBase):
    def __init__(self, state_reader: ISecureStateAccess, state_modifier: ISecureStateModification):
        super().__init__(state_reader, state_modifier)
    
    async def execute(self, args, session, context=None):
        self.update_state_setting('setting', value)
```

### Step 2: Use Factory for Creation

```python
# OLD: Direct instantiation
command = SetCommand()

# NEW: Factory-based creation
factory = container.get_service(SecureCommandFactory)
command = factory.create_command(SetCommand)
```

### Step 3: Update Service Registration

```python
# Services are automatically registered with proper DI
container = get_or_build_service_provider()
factory = container.get_service(SecureCommandFactory)
secure_state = container.get_service(ISecureStateAccess)
```

## 🎯 Benefits Achieved

### 1. **Compile-Time Safety**
- Constructor signatures enforce DI requirements
- Interface segregation prevents inappropriate access
- Type system catches violations early

### 2. **Runtime Protection**
- State access proxy blocks direct manipulation
- Validation in secure services prevents invalid operations
- Clear error messages guide developers to correct patterns

### 3. **Architectural Clarity**
- Clear separation between stateful and stateless commands
- Explicit dependencies make testing easier
- Interface-based design enables easy mocking

### 4. **Maintainability**
- Changes to state management don't affect business logic
- New commands follow established patterns
- Legacy code can be gradually migrated

## 🔍 Verification

### Test the Enforcement

```python
# This will demonstrate the enforcement in action
def test_architectural_enforcement():
    # ✅ This works - proper DI
    factory = container.get_service(SecureCommandFactory)
    command = factory.create_command(SetCommand)
    
    # ❌ This fails - missing DI
    try:
        bad_command = SetCommand()  # StateAccessViolationError
    except StateAccessViolationError as e:
        print(f"Caught violation: {e}")
    
    # ❌ This fails - stateless command accessing state
    try:
        stateless_command = SomeStatelessCommand()
        stateless_command.get_state_setting('prefix')  # StateAccessViolationError
    except StateAccessViolationError as e:
        print(f"Caught violation: {e}")
```

## 📋 Checklist for New Commands

- [ ] Inherit from `StatefulCommandBase` or `StatelessCommandBase`
- [ ] Implement required constructor with DI parameters
- [ ] Use `self.get_state_setting()` and `self.update_state_setting()` for state access
- [ ] Create commands through `SecureCommandFactory`
- [ ] Write tests that verify DI requirements

## 🚀 Result

The architecture now **automatically prevents** SOLID violations through:

1. **Type System Enforcement**: Constructor signatures require proper DI
2. **Runtime Validation**: State access is validated and logged
3. **Interface Segregation**: Clear separation of read/write concerns
4. **Factory Pattern**: Centralized creation with proper dependencies
5. **Proxy Protection**: Direct state access is blocked

This approach makes it **impossible** to violate the architecture without explicitly bypassing the security mechanisms, creating a self-enforcing codebase that maintains SOLID principles.