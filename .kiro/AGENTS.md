# Kiro Spec-Driven Development - Agent Guidelines

This document provides comprehensive guidance for AI agents on using the Kiro-inspired spec-driven development workflow in this project.

---

## Overview

**Kiro** is a structured, phase-based approach to feature development that separates **thinking** (requirements, design) from **coding** (implementation). It ensures high-quality, well-planned features through systematic progression from requirements to implementation.

## Scope (Opt-In)

This guide applies **only** when the user explicitly opts into Kiro spec workflow (e.g., invokes `/kiro:*`, references a spec name/path under `.kiro/specs/`, or asks for spec-driven development).

If the user did not explicitly mention Kiro/specs, follow normal engineering workflow and treat Kiro as optional guidance (see `AGENTS.md` in the repo root).

### Core Philosophy

- **Spec-first, code-second**: No implementation until requirements and design are approved
- **Phase separation**: Each phase has distinct objectives and outputs
- **Project memory**: Steering files capture patterns and principles, not exhaustive lists
- **Test-driven**: All implementation follows TDD (Red → Green → Refactor)
- **Traceability**: Every task maps to requirements, every requirement maps to acceptance criteria

---

## Directory Structure

```
.kiro/
├── specs/                          # Feature specifications
│   └── {feature-name}/
│       ├── spec.json               # Metadata, phase tracking, approvals
│       ├── requirements.md         # EARS-format requirements
│       ├── design.md              # Technical design document
│       ├── tasks.md               # Implementation task breakdown
│       └── research.md            # Discovery findings and investigations
│
├── steering/                       # Project memory (persistent)
│   ├── product.md                 # Purpose, value, capabilities
│   ├── tech.md                    # Stack, conventions, decisions
│   ├── structure.md               # Organization, naming, patterns
│   └── {custom}.md                # Domain-specific steering (API, testing, etc.)
│
└── settings/                       # Templates and rules (DO NOT document in steering)
    ├── templates/                  # Starting structures
    │   ├── specs/                 # Spec document templates
    │   ├── steering/              # Core steering templates
    │   └── steering-custom/       # Domain-specific templates
    └── rules/                      # Process guidelines
        ├── ears-format.md         # Requirements syntax
        ├── design-principles.md   # Design standards
        ├── tasks-generation.md    # Task breakdown rules
        ├── steering-principles.md # Project memory guidelines
        └── ...                    # Other process rules
```

---

## Kiro Workflow: Sequential Phases

### Phase 0: Steering Setup (First-Time Only)

**Command**: `/kiro:steering`

**Purpose**: Bootstrap project memory from existing codebase.

**When to use**:
- First time using Kiro in this project
- Steering directory is empty or missing core files

**Process**:
1. Analyzes codebase structure, patterns, and conventions
2. Generates `product.md`, `tech.md`, `structure.md` in `.kiro/steering/`
3. Captures patterns (not exhaustive lists) following granularity principles
4. User reviews and approves as Source of Truth

**Output**: Core steering files capturing project patterns and principles.

**Notes**:
- Steering is project memory, loaded during all spec generation phases
- Updates are additive (preserve user customizations)
- Focus on patterns that guide decisions, not file/dependency catalogs

---

### Phase 1: Spec Initialization

**Command**: `/kiro:spec-init <project-description>`

**Purpose**: Create feature directory and metadata.

**Process**:
1. Generate unique feature name from description
2. Check `.kiro/specs/` for conflicts (append suffix if needed)
3. Create `.kiro/specs/{feature-name}/` directory
4. Initialize files:
   - `spec.json` (metadata, phase tracking)
   - `requirements.md` (template with project description)

**Output**:
- Feature directory created
- Metadata initialized
- Ready for requirements generation

**Example**:
```bash
/kiro:spec-init Add OAuth2 authentication with Google and GitHub providers
```

**Important**: This phase only creates structure. No requirements/design/tasks generated yet.

---

### Phase 2: Requirements Generation

**Command**: `/kiro:spec-requirements <feature-name>`

**Purpose**: Generate comprehensive, testable requirements in EARS format.

**Process**:
1. Load context:
   - `spec.json` for metadata
   - `requirements.md` for project description
   - **ALL steering files** from `.kiro/steering/` (project memory)
2. Read guidelines:
   - `.kiro/settings/rules/ears-format.md` (syntax rules)
   - `.kiro/settings/templates/specs/requirements.md` (structure)
3. Generate requirements:
   - Use EARS patterns (When/If/While/Where/The system shall)
   - Focus on WHAT, not HOW
   - Make testable and verifiable
   - Use language specified in `spec.json`
4. Update metadata:
   - Set `phase: "requirements-generated"`
   - Set `approvals.requirements.generated: true`

**Output**: Complete `requirements.md` with EARS-formatted acceptance criteria.

**EARS Format Examples**:
- **Event-driven**: "When user clicks checkout button, the Checkout Service shall validate cart contents"
- **State-driven**: "While payment is processing, the Checkout Service shall display loading indicator"
- **Error handling**: "If invalid credit card number is entered, then the website shall display error message"

**Critical Rules**:
- All requirement headings MUST include numeric IDs (e.g., "Requirement 1", "2. Feature X")
- No alphabetic IDs like "Requirement A"
- Requirements must be testable, verifiable, single behavior

**Next Step**: User reviews requirements. If approved, proceed to design phase.

---

### Phase 2.5: Gap Analysis (Optional, Recommended for Brownfield)

**Command**: `/kiro:validate-gap <feature-name>`

**Purpose**: Analyze implementation gap between requirements and existing codebase.

**When to use**:
- Extending existing systems (brownfield projects)
- Need to understand integration points
- Evaluating implementation approaches

**Process**:
1. Load requirements and steering context
2. Read `.kiro/settings/rules/gap-analysis.md` for framework
3. Analyze existing codebase using Grep/Read tools
4. Evaluate implementation approaches:
   - **Option A**: Extend existing components
   - **Option B**: Create new components
   - **Option C**: Hybrid approach
5. Assess complexity (S/M/L/XL) and risk (High/Medium/Low)

**Output**: Gap analysis document with:
- Current state investigation
- Requirement-to-asset mapping
- Multiple viable implementation options
- Effort/risk assessment
- Research items for design phase

**Note**: Skip for greenfield projects or simple features.

---

### Phase 3: Design Generation

**Command**: `/kiro:spec-design <feature-name> [-y]`

**Purpose**: Create comprehensive technical design translating requirements (WHAT) into architecture (HOW).

**Flags**:
- `-y`: Auto-approve requirements and proceed

**Process**:
1. **Load Context**:
   - Spec files (`spec.json`, `requirements.md`, existing `design.md`)
   - **ALL steering files** from `.kiro/steering/`
   - Templates and rules from `.kiro/settings/`
2. **Discovery & Analysis** (critical phase):
   - Classify feature type (new/extension/simple/complex)
   - Execute appropriate discovery:
     - **Complex/New**: Full discovery (`.kiro/settings/rules/design-discovery-full.md`)
     - **Extensions**: Light discovery (`.kiro/settings/rules/design-discovery-light.md`)
     - **Simple**: Quick pattern check only
   - Use external research (docs/standards) when needed for:
     - Latest architectural patterns
     - External API documentation
     - Technology updates and best practices
     - Security considerations
   - Use Grep to analyze existing codebase patterns
3. **Persist Findings**:
   - Create/update `.kiro/specs/{feature-name}/research.md`
   - Document investigations, decisions, trade-offs
   - Capture architecture pattern evaluation
4. **Generate Design Document**:
   - Follow `.kiro/settings/templates/specs/design.md` structure
   - Apply `.kiro/settings/rules/design-principles.md` principles
   - Integrate all discovery findings
   - Use language specified in `spec.json`
5. **Update Metadata**:
   - Set `phase: "design-generated"`
   - Set `approvals.design.generated: true`
   - Set `approvals.requirements.approved: true`

**Output**:
- Complete `design.md` with architecture, components, interfaces
- `research.md` with discovery findings and decisions

**Critical Constraints**:
- **Type Safety Mandatory**: No `any` in TypeScript, use type hints in Python
- **Design Focus**: Architecture and interfaces ONLY, no implementation code
- **Requirements Traceability**: Use numeric IDs only (e.g., "1.1", "2.3")
- **Latest Information**: Use up-to-date vendor docs/standards for external dependencies (when applicable)
- **Steering Alignment**: Respect existing patterns from steering context

**Key Sections in design.md**:
- Overview & Goals/Non-Goals
- Requirements Traceability (map requirements to components)
- Architecture Pattern & Boundary Map
- Technology Stack & Alignment
- System Flows (Mermaid diagrams)
- Components & Interface Contracts
- Data Models
- Error Handling, Testing, Security, Performance

**Next Step**: User reviews design. Optionally run `/kiro:validate-design` for quality review.

---

### Phase 3.5: Design Validation (Optional)

**Command**: `/kiro:validate-design <feature-name>`

**Purpose**: Interactive quality review of technical design.

**Process**:
1. Load design, requirements, steering context
2. Read `.kiro/settings/rules/design-review.md` for criteria
3. Execute review: Analysis → Critical Issues → Strengths → GO/NO-GO
4. Engage interactively with user

**Output**:
- Review summary
- Maximum 3 critical issues
- Design strengths
- GO/NO-GO decision with rationale

**Note**: Validation is recommended but optional. Helps catch issues early.

---

### Phase 4: Task Generation

**Command**: `/kiro:spec-tasks <feature-name> [-y] [--sequential]`

**Purpose**: Generate detailed, actionable implementation tasks.

**Flags**:
- `-y`: Auto-approve requirements and design
- `--sequential`: Omit parallel markers (default: parallel analysis enabled)

**Process**:
1. **Load Context**:
   - Spec files (`spec.json`, `requirements.md`, `design.md`, existing `tasks.md`)
   - **ALL steering files** from `.kiro/steering/`
2. **Load Generation Rules**:
   - `.kiro/settings/rules/tasks-generation.md` (core principles)
   - `.kiro/settings/rules/tasks-parallel-analysis.md` (parallel criteria)
   - `.kiro/settings/templates/specs/tasks.md` (format)
3. **Generate Task List**:
   - Map ALL requirements to tasks
   - Natural language descriptions (what to do, not code structure)
   - Task sizing: 1-3 hours per sub-task
   - Maximum 2 levels (major tasks + sub-tasks)
   - Sequential numbering (1, 2, 3..., never repeat)
   - Apply `(P)` markers for parallel-capable tasks
   - Mark optional test coverage with `- [ ]*` when appropriate
4. **Update Metadata**:
   - Set `phase: "tasks-generated"`
   - Set `approvals.tasks.generated: true`

**Output**: Complete `tasks.md` with implementation task breakdown.

**Task Format**:
```markdown
- [ ] 1. Major task description
- [ ] 1.1 (P) Sub-task description
  - Detail item 1
  - Detail item 2
  - _Requirements: 1.1, 1.3_

- [ ] 1.2 Sub-task description
  - Detail items...
  - _Requirements: 2.1_

- [ ] 2. Next major task
- [ ] 2.1 (P) Sub-task...
```

**Critical Rules**:
- **Natural Language**: Describe capabilities, not file paths or method names
- **Task Integration**: Every task builds on previous outputs
- **Complete Coverage**: ALL requirements must map to tasks
- **Requirement IDs**: List numeric IDs only (comma-separated, no descriptions)
- **Parallel Markers**: `(P)` for tasks with no dependencies/conflicts

**Next Step**: User reviews tasks. If approved, proceed to implementation.

---

### Phase 5: Implementation

**Command**: `/kiro:spec-impl <feature-name> [task-numbers]`

**Purpose**: Execute implementation tasks using Test-Driven Development.

**Arguments**:
- No task numbers: Execute all pending tasks (NOT recommended - context bloat)
- Single task: `/kiro:spec-impl feature-name 1.1` (recommended)
- Multiple tasks: `/kiro:spec-impl feature-name 1.1,1.2` (use cautiously)

**Process (TDD Cycle)**:
1. **Load Context**:
   - Spec files (`spec.json`, `requirements.md`, `design.md`, `tasks.md`)
   - **ALL steering files** from `.kiro/steering/`
2. **Select Tasks**: Determine which tasks to execute
3. **For Each Task, Execute TDD**:
   - **RED**: Write failing test first
   - **GREEN**: Write minimal code to make test pass
   - **REFACTOR**: Clean up code structure
   - **VERIFY**: All tests pass (new + existing)
   - **MARK COMPLETE**: Update checkbox `- [ ]` → `- [x]` in `tasks.md`

**Critical Constraints**:
- **TDD Mandatory**: Tests MUST be written before implementation code
- **Task Scope**: Implement only what the specific task requires
- **Test Coverage**: All new code must have tests
- **No Regressions**: Existing tests must continue to pass
- **Design Alignment**: Implementation must follow `design.md` specifications

**Post-Edit QA (MANDATORY)**:
After editing ANY Python file, immediately run:
```powershell
./.venv/Scripts/python.exe -m ruff check --fix <file> && ./.venv/Scripts/python.exe -m black <file> && ./.venv/Scripts/python.exe -m mypy <file>
```

**Important**: Clear conversation history between tasks to free up context and ensure clean state.

**Next Step**: Continue implementing tasks. Run `/kiro:validate-impl` to validate completion.

---

### Phase 5.5: Implementation Validation (Optional)

**Command**: `/kiro:validate-impl [feature-name] [task-numbers]`

**Purpose**: Verify implementation aligns with requirements, design, and tasks.

**Arguments**:
- No arguments: Auto-detect from conversation history
- Feature only: Validate all completed tasks in feature
- Feature + tasks: Validate specific tasks

**Process**:
1. Detect validation target (conversation history or arguments)
2. Load context (spec files, steering)
3. Execute validation:
   - Task completion check (checkbox marked `[x]`)
   - Test coverage check (tests exist and pass)
   - Requirements traceability (EARS requirements covered)
   - Design alignment (structure matches design)
   - Regression check (no broken existing tests)
4. Generate report with GO/NO-GO decision

**Output**:
- Validation summary by feature
- Coverage report (tasks, requirements, design)
- Issues and deviations with severity
- GO/NO-GO decision

**Note**: Validation is recommended after implementation to ensure quality.

---

## Status and Monitoring

**Command**: `/kiro:spec-status <feature-name>`

**Purpose**: Display comprehensive status and progress for a specification.

**Output**:
- Current phase and completion status
- Task breakdown (completed/remaining)
- Next actions and blockers
- Approval status for each phase

**Example Output**:
```
Feature: user-authentication
Phase: tasks-generated
Progress: Requirements ✅ | Design ✅ | Tasks ⏳ (5/12 completed)
Next: /kiro:spec-impl user-authentication 2.1
```

---

## Steering Management

### Bootstrap Steering (First-Time)

**Command**: `/kiro:steering`

**When**: `.kiro/steering/` is empty or missing core files

**Process**:
1. Analyze codebase (JIT - Just-In-Time)
2. Extract patterns (not exhaustive lists)
3. Generate core files: `product.md`, `tech.md`, `structure.md`
4. Present summary for review

### Sync Steering (Maintenance)

**Command**: `/kiro:steering`

**When**: Core files exist, codebase has evolved

**Process**:
1. Load existing steering files
2. Analyze codebase for changes
3. Detect drift (steering ↔ code)
4. Propose additive updates (preserve user content)
5. Report updates, warnings, recommendations

### Custom Steering

**Command**: `/kiro:steering-custom`

**Purpose**: Create domain-specific steering files.

**Available Templates**:
- `api-standards.md` - REST/GraphQL conventions
- `testing.md` - Test organization, mocking
- `security.md` - Auth patterns, input validation
- `database.md` - Schema design, migrations
- `error-handling.md` - Error types, logging
- `authentication.md` - Auth flows, permissions
- `deployment.md` - CI/CD, environments

**Process**:
1. Ask user for domain/topic
2. Check if template exists in `.kiro/settings/templates/steering-custom/`
3. Analyze codebase for relevant patterns
4. Generate custom steering file in `.kiro/steering/`

---

## Key Principles for Agents

### 1. Steering Granularity

**Golden Rule**: "If new code follows existing patterns, steering shouldn't need updating."

**Document**:
- ✅ Organizational patterns (feature-first, layered)
- ✅ Naming conventions (PascalCase rules)
- ✅ Architectural decisions (state management)
- ✅ Technology standards (key frameworks)

**Avoid**:
- ❌ Complete file listings
- ❌ Every component description
- ❌ All dependencies
- ❌ Implementation details
- ❌ Agent-specific tooling directories (`.cursor/`, `.gemini/`, `.claude/`)
- ❌ Detailed documentation of `.kiro/` metadata directories (settings, automation)

### 2. EARS Requirements Format

**Use appropriate patterns**:
- **Event-driven**: `When [event], the [system] shall [response/action]`
- **State-driven**: `While [precondition], the [system] shall [response/action]`
- **Error handling**: `If [trigger], then the [system] shall [response/action]`
- **Optional features**: `Where [feature is included], the [system] shall [response/action]`
- **Always-active**: `The [system] shall [response/action]`

**Subject Selection**:
- Software projects: Use concrete system/service name (e.g., "Checkout Service")
- Process/workflow: Use responsible team/role (e.g., "Support Team")

### 3. Design Principles

**Core Rules**:
- **Type Safety is Mandatory**: No `any` in TypeScript, use type hints in Python
- **Design vs Implementation**: Focus on WHAT, not HOW
- **Visual Communication**: Use Mermaid diagrams (pure Mermaid only, no styling)
- **Single Responsibility**: One clear purpose per component
- **Requirements Traceability**: Use numeric IDs only (e.g., "1.1", "2.3")

**Mermaid Requirements**:
- ✅ Plain Mermaid only (no custom styling)
- ✅ Alphanumeric node IDs only (no `@`, `/`, `-`)
- ✅ Simple labels (no parentheses, brackets, quotes, slashes)
- ❌ Invalid: `DnD[@dnd-kit/core]`, `UI[KanbanBoard(React)]`
- ✅ Valid: `DndKit[dnd-kit core]`

### 4. Task Generation Rules

**Core Principles**:
- **Natural Language**: Describe capabilities, not code structure
- **Task Integration**: Every task builds on previous outputs
- **Flexible Sizing**: 1-3 hours per sub-task, 3-10 details per sub-task
- **Requirements Mapping**: End each task with `_Requirements: X.X, Y.Y_` (numeric IDs only)
- **Code-Only Focus**: Only coding, testing, technical setup (no deployment/docs)

**Task Hierarchy**:
- Maximum 2 levels (major tasks + sub-tasks)
- Sequential numbering (1, 2, 3..., never repeat)
- Collapse single-subtask structures

**Parallel Analysis** (default enabled):
- Append `(P)` after task number for parallel-capable tasks
- Criteria: No data dependency, no shared resource contention, no prerequisite review
- Omit `(P)` in `--sequential` mode

### 5. TDD Implementation

**Mandatory Cycle**:
1. **RED**: Write failing test first
2. **GREEN**: Write minimal code to pass
3. **REFACTOR**: Clean up structure
4. **VERIFY**: All tests pass
5. **MARK COMPLETE**: Update checkbox in `tasks.md`

**Post-Edit QA** (MANDATORY):
```powershell
./.venv/Scripts/python.exe -m ruff check --fix <file> && ./.venv/Scripts/python.exe -m black <file> && ./.venv/Scripts/python.exe -m mypy <file>
```

### 6. Context Management

**Load ALL steering files** during:
- Requirements generation
- Design generation
- Task generation
- Implementation

**Steering provides**:
- Project patterns and conventions
- Architecture decisions and standards
- Technology stack and frameworks
- Naming and organization rules

**Clear context between tasks**:
- Frees up context window
- Ensures clean state
- Prevents context bloat

---

## Example Workflow: Complete Feature

### Scenario: Add OAuth2 Authentication

**Step 1: Initialize Spec**
```bash
/kiro:spec-init Add OAuth2 authentication with Google and GitHub providers supporting PKCE flow
```
→ Creates `.kiro/specs/oauth2-authentication/` with metadata

**Step 2: Generate Requirements**
```bash
/kiro:spec-requirements oauth2-authentication
```
→ Generates `requirements.md` with EARS-formatted acceptance criteria
→ User reviews and approves

**Step 3: (Optional) Gap Analysis**
```bash
/kiro:validate-gap oauth2-authentication
```
→ Analyzes existing auth infrastructure
→ Identifies reusable components and integration points
→ Recommends implementation approach

**Step 4: Generate Design**
```bash
/kiro:spec-design oauth2-authentication -y
```
→ Conducts full discovery (external research for OAuth2 best practices)
→ Generates `design.md` with architecture, components, interfaces
→ Creates `research.md` with discovery findings

**Step 5: (Optional) Validate Design**
```bash
/kiro:validate-design oauth2-authentication
```
→ Interactive quality review
→ GO/NO-GO decision with rationale

**Step 6: Generate Tasks**
```bash
/kiro:spec-tasks oauth2-authentication -y
```
→ Generates `tasks.md` with implementation breakdown
→ Maps all requirements to tasks
→ Marks parallel-capable tasks with `(P)`

**Step 7: Implement Tasks**
```bash
# Clear context first, then implement first task
/kiro:spec-impl oauth2-authentication 1.1

# Clear context, implement next task
/kiro:spec-impl oauth2-authentication 1.2

# Continue until all tasks complete
```
→ Follows TDD cycle for each task
→ Marks tasks complete in `tasks.md`

**Step 8: (Optional) Validate Implementation**
```bash
/kiro:validate-impl oauth2-authentication
```
→ Verifies requirements coverage
→ Checks test coverage and design alignment
→ GO/NO-GO decision

**Step 9: Check Status**
```bash
/kiro:spec-status oauth2-authentication
```
→ Shows completion status and next actions

---

## Common Scenarios

### When to Use Kiro

**✅ Use Kiro for**:
- New features requiring structured design
- Breaking changes or architecture shifts
- Complex integrations or unclear requirements
- Features needing requirements analysis
- Brownfield projects requiring gap analysis

**❌ Code directly for**:
- Quick fixes or trivial changes
- Simple bugs with clear solutions
- User explicitly says "just code this"
- Minor adjustments or refactoring

### Greenfield vs Brownfield

**Greenfield** (new project):
- Skip gap analysis (`/kiro:validate-gap`)
- Use full discovery in design phase
- Focus on architecture patterns and technology selection

**Brownfield** (existing project):
- Run gap analysis (`/kiro:validate-gap`) after requirements
- Use light discovery in design phase (focus on integration)
- Respect existing patterns from steering context

### Handling Approvals

**Manual approval** (default):
- User reviews each phase output
- Provides feedback or approval
- Agent regenerates if modifications needed

**Auto-approval** (use `-y` flag):
- Agent automatically approves previous phases
- Useful for rapid iteration
- Example: `/kiro:spec-design feature-name -y`

---

## Project-Specific Context

### Universal LLM Proxy Architecture

**Key Constraints** (from steering):
- **Async FastAPI**: Use `async/await` patterns
- **DI Integration**: Services registered via `ServiceCollection`
- **Error Hierarchy**: Exceptions extend `LLMProxyError`
- **Config Precedence**: CLI > ENV > YAML
- **Staged Initialization**: Infrastructure → Services → Backends → Controllers

**Important Paths**:
- `src/core/cli.py` - Entry point
- `src/core/app/stages/` - Startup logic
- `src/connectors/` - Backend implementations
- `src/core/simulation/` - Debugging tools
- `var/wire_captures_cbor/` - CBOR traffic captures
- `scripts/` - End-user tools
- `dev/scripts/` - Development tools & artifacts

**Testing Requirements**:
- TDD mandatory (test → fail → code → pass)
- Run related tests first
- Run full suite after multi-file changes
- Post-edit QA: ruff + black + mypy

---

## Troubleshooting

### Spec Not Found
**Issue**: Command fails with "No spec found"
**Solution**: Check `.kiro/specs/` directory, ensure feature name is correct

### Missing Templates
**Issue**: Template files not found
**Solution**: Check `.kiro/settings/templates/` directory, restore from repository

### Requirements Not Approved
**Issue**: Design generation blocked
**Solution**: Use `-y` flag or manually approve in `spec.json`

### Context Bloat
**Issue**: Slow responses, memory issues
**Solution**: Clear conversation history between tasks, implement one task at a time

### Invalid Requirement IDs
**Issue**: Tasks reference non-numeric requirement IDs
**Solution**: Fix `requirements.md` to use numeric IDs (1, 2, 3...), regenerate tasks

---

## Security and Best Practices

### Security Guidelines
- **Never include** in steering or specs:
  - API keys, passwords, credentials
  - Database URLs, internal IPs
  - Secrets or sensitive data

### Quality Standards
- **Single domain**: One topic per file
- **Concrete examples**: Show patterns with code
- **Explain rationale**: Why decisions were made
- **Maintainable size**: 100-200 lines typical for steering

### Preservation (when updating)
- Preserve user sections and custom examples
- Additive by default (add, don't replace)
- Add `updated_at` timestamp
- Note why changes were made

---

## Quick Reference

### Essential Commands

| Command | Purpose |
|---------|---------|
| `/kiro:steering` | Bootstrap/sync project memory |
| `/kiro:spec-init <desc>` | Initialize new spec |
| `/kiro:spec-requirements <name>` | Generate requirements |
| `/kiro:validate-gap <name>` | Analyze implementation gap (optional) |
| `/kiro:spec-design <name> [-y]` | Generate design |
| `/kiro:validate-design <name>` | Validate design quality (optional) |
| `/kiro:spec-tasks <name> [-y] [--sequential]` | Generate tasks |
| `/kiro:spec-impl <name> [tasks]` | Implement tasks (TDD) |
| `/kiro:validate-impl [name] [tasks]` | Validate implementation (optional) |
| `/kiro:spec-status <name>` | Show status and progress |

### Key Files

| File | Purpose |
|------|---------|
| `spec.json` | Metadata, phase tracking, approvals |
| `requirements.md` | EARS-formatted requirements |
| `design.md` | Technical design document |
| `tasks.md` | Implementation task breakdown |
| `research.md` | Discovery findings and decisions |

### Phase Progression

```
Initialize → Requirements → (Gap Analysis) → Design → (Design Validation) → Tasks → Implementation → (Implementation Validation)
     ↓            ↓              ↓              ↓            ↓              ↓            ↓                    ↓
  spec-init  spec-requirements validate-gap spec-design validate-design spec-tasks spec-impl        validate-impl
```

---

## Additional Resources

### Settings Directory Structure
- `.kiro/settings/templates/` - Starting structures for specs and steering
- `.kiro/settings/rules/` - Process guidelines and quality criteria

### Key Rules Documents
- `ears-format.md` - Requirements syntax patterns
- `design-principles.md` - Design standards and quality metrics
- `tasks-generation.md` - Task breakdown rules and sizing
- `steering-principles.md` - Project memory granularity guidelines
- `gap-analysis.md` - Implementation gap analysis framework
- `design-discovery-full.md` - Comprehensive research process
- `design-discovery-light.md` - Lightweight discovery for extensions

### Templates
- `specs/` - Spec document templates (init.json, requirements.md, design.md, tasks.md, research.md)
- `steering/` - Core steering templates (product.md, tech.md, structure.md)
- `steering-custom/` - Domain-specific templates (api-standards, testing, security, etc.)

---

## Summary

**Kiro** provides a structured, phase-based approach to feature development that ensures high-quality, well-planned implementations. By separating thinking (requirements, design) from coding (implementation), it reduces rework, improves traceability, and maintains consistency across the project.

**Key Takeaways**:
1. **Spec-first**: No code until requirements and design are approved
2. **Phase separation**: Each phase has distinct objectives and outputs
3. **Project memory**: Steering captures patterns that guide decisions
4. **TDD mandatory**: All implementation follows Red → Green → Refactor
5. **Traceability**: Every task maps to requirements, every requirement has acceptance criteria

**When in doubt**: Follow the sequential workflow, load steering context, use EARS format for requirements, apply TDD for implementation, and clear context between tasks.
