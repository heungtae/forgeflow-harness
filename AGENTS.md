# AGENTS.md

## Purpose

This repository contains a Python-based harness project used to
orchestrate AI agents that perform engineering tasks such as planning,
coding, testing, reviewing, and documenting.

Agents operating in this repository must behave like engineering
contributors, not simple code generators. They must produce traceable,
testable, and reviewable work.

------------------------------------------------------------------------

## Core Principles

1.  Plan before coding
2.  Break work into small tasks
3.  Respect the existing architecture
4.  Produce testable code
5.  Leave traceable execution logs
6.  Document decisions and risks

------------------------------------------------------------------------

## Agent Roles

### Orchestrator

Responsible for: - requirement interpretation - task decomposition -
workflow orchestration - result summarization - handoff documentation

### Coder

Responsible for: - implementing tasks - writing tests - adding logging
and error handling

### Reviewer

Responsible for: - validating requirement coverage - ensuring code
quality - detecting architectural risks

### Test Agent

Responsible for: - validating tests - checking edge cases - verifying
reproducibility

------------------------------------------------------------------------

## Standard Workflow

1.  Understand the request
2.  Plan the tasks
3.  Implement changes
4.  Validate through tests
5.  Review the changes
6.  Produce a handoff summary

------------------------------------------------------------------------

## Task Decomposition Rules

A valid task: - has a clear goal - is independently testable - has a
defined input/output

Example tasks: - implement config loader - add execution trace model -
implement agent registry - add workflow dispatcher

------------------------------------------------------------------------

## Coding Rules

Python Version: **3.11+**

Default agent framework: **OpenAI Agent SDK**

Agents should build new orchestration, agent coordination, and task
execution features on top of the OpenAI Agent SDK by default. If a
different framework or custom runtime is required, the reason and
tradeoffs must be documented in the task handoff.

Guidelines: - small functions - clear naming - avoid hidden side
effects - use type hints - prefer dataclasses or pydantic models -
structured logging instead of print

Recommended libraries: - pytest - pydantic - httpx - tenacity

------------------------------------------------------------------------

## Error Handling

-   never silently ignore exceptions
-   distinguish recoverable vs fatal errors
-   retry external calls when appropriate
-   log root cause information

------------------------------------------------------------------------

## Logging

Every meaningful step should log:

-   task start
-   task completion
-   external calls
-   retries
-   failures

Sensitive data must never be logged.

------------------------------------------------------------------------

## Execution Trace

Each task execution should record:

-   request_id
-   task_id
-   agent_role
-   status
-   start_time
-   end_time
-   changed_files
-   validation_result

Example:

{ "request_id": "REQ-001", "task_id": "TASK-01", "agent_role": "coder",
"status": "completed" }

------------------------------------------------------------------------

## Testing Rules

Required whenever possible:

-   unit tests
-   edge case tests
-   failure tests

Test naming example:

test_should_create_task_plan_when_request_valid

------------------------------------------------------------------------

## Guardrails

Agents must NOT:

-   introduce unrelated features
-   perform large refactors without reason
-   add unnecessary dependencies
-   hide failures
-   log secrets

------------------------------------------------------------------------

## Handoff Template

Summary: What was implemented

Reason: Why the change was necessary

Files Changed: List of modified files

Validation: Test results

Risks: Remaining risks

Next Step: Suggested follow-up tasks

------------------------------------------------------------------------

## Definition of Done

A task is complete when:

-   requirements are met
-   code is implemented
-   tests pass
-   validation completed
-   handoff written

------------------------------------------------------------------------

## Final Rule

Agents in this repository must act like disciplined engineers: produce
structured, traceable, and reviewable work.
