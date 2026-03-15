# Codex Harness Orchestration Architecture Design
Generated: 2026-03-15T10:34:04.614778

## 1. Overview
This document describes the architecture for building an AI coding harness using Codex with a custom orchestration layer.
The goal is to support:
- Task decomposition
- Multi‑agent workflow (Coder / Reviewer / Fixer)
- Guardrails and safety policies
- Execution tracing
- Handoff between agents
- Multi‑step orchestration

The Codex App Server acts as the execution engine while the orchestration service manages workflow logic.

## 2. High-Level Architecture

```
User / Github Issue / Jira / Web 
        |
        v
Ingress API (Task Intake)
        |
        v
Orchestrator Service
  - task decomposition
  - workflow state machine
  - guardrails
  - trace correlation
        |
        v
Codex Adapter / Session Manager
        |
        v
Codex App Server
        |
        v
Workspace Harness
  - git worktree
  - build/test/lint
  - artifact collection
```

## 3. Components

### 3.1 Ingress Layer
Receives requests from:
- Github Issue
- CLI
- REST API

Example request format:

```json
{
  "request_id": "req-20260313-001",
  "repo": "prod-system-api",
  "goal": "Fix issue JIRA-123 and prepare PR",
  "constraints": {
    "allow_db_schema_change": false,
    "network": "restricted"
  }
}
```

### 3.2 Orchestrator Service
Responsibilities:
- Workflow state machine
- Task graph creation
- Agent handoff
- Guardrail enforcement
- Trace collection

States:
NEW → DECOMPOSED → CODING → VALIDATING → REVIEWING → NEEDS_FIX → READY_FOR_PR → DONE

Runtime settings for the orchestrator should be defined in `config.toml`.
This file should own guardrail defaults, session policies, workspace limits, and integration endpoints.

### 3.3 Codex Adapter
Abstracts interaction with Codex App Server.

Internal API:
```
POST /sessions
POST /sessions/{id}/run
POST /sessions/{id}/reply
POST /sessions/{id}/approve
GET  /sessions/{id}/events
POST /sessions/{id}/terminate
```

### 3.4 Workspace Harness
Manages execution environment.

Functions:
- git clone or checkout
- git worktree creation
- branch creation
- build/test execution
- artifact collection

### 3.5 Tool Layer
External integrations via MCP.

Examples:
- Jira MCP
- GitHub MCP
- Documentation search MCP
- Test report MCP

## 4. Agent Roles

### 4.1 Decomposition Agent
Analyzes request and generates task graph.

Example output:

```json
{
  "tasks": [
    { "id": "T1", "goal": "root cause analysis" },
    { "id": "T2", "goal": "implement fix", "depends_on": ["T1"] },
    { "id": "T3", "goal": "add regression test", "depends_on": ["T2"] }
  ]
}
```

### 4.2 Coder Agent
- Modify code
- Run commands
- Fix lint/test failures

### 4.3 Reviewer Agent
- Review diffs
- Evaluate risk
- Check architecture rules
- Generate PR summary

### 4.4 Fixer Agent
- Resolve issues raised by reviewer
- Re-run validation

## 5. Guardrails

### File Policy
```
src/main/** -> allow
db/migration/** -> approval required
.env* -> deny
```

### Command Policy
Allowed:
- mvn *
- git status
- git diff

Denied:
- rm -rf *
- sudo *
- curl | sh

### Quality Gates
- Linter must pass
- Unit tests must pass
- Static analysis must pass

The guardrail and execution policy rules above should be loaded from `config.toml` so the harness can be tuned without changing code.

## 6. Execution Trace

Trace schema:

```json
{
  "trace_id": "tr-001",
  "agent": "coder",
  "event": "command_finished",
  "timestamp": "2026-03-13T21:15:00",
  "payload": {
    "command": "mvn test",
    "exit_code": 0
  }
}
```

Trace events:
- workflow_started
- task_decomposed
- handoff_started
- command_started
- command_finished
- validation_passed
- validation_failed
- review_passed
- review_failed
- workflow_done

## 7. Multi‑Step Orchestration Flow

1. Intake request
2. Task decomposition
3. Session allocation
4. Coding loop
5. Validation
6. Review loop
7. Fix loop if needed
8. Human approval if required
9. PR preparation
10. Workflow completion

## 8. Recommended Technology Stack

Control Layer
- Agents SDK or Spring Boot orchestration service
- Redis for queue/lock
- PostgreSQL for state storage

Execution Layer
- Codex App Server
- Git worktree
- Maven/Gradle
- Container sandbox

Observability
- OpenTelemetry
- Grafana/Loki

Integration
- Jira MCP
- GitHub MCP
- Documentation MCP

## 9. Deployment Model

```
orchestrator service
policy service
trace collector
codex adapter
codex app-server
workspace volume
```

Sessions should be pooled by repository or user to reduce startup cost.

## 10. Implementation Roadmap

Week 1
- Codex adapter
- Session management
- Workspace manager

Week 2
- Decomposition agent
- Coding loop
- Quality gate integration

Week 3
- Reviewer agent
- Guardrail engine
- Trace storage

Week 4
- Jira integration
- PR automation
- Approval UI

## 11. Key Design Principle

Codex App Server provides execution capability,
while the orchestration service manages workflow logic,
guardrails, and multi‑agent coordination.
