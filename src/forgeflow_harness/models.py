from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class HarnessRequest:
    request_id: str
    repo: str
    goal: str
    constraints: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        missing: list[str] = []
        if not self.request_id.strip():
            missing.append("request_id")
        if not self.repo.strip():
            missing.append("repo")
        if not self.goal.strip():
            missing.append("goal")
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")


@dataclass(slots=True)
class HarnessConfig:
    codex_base_url: str
    codex_timeout_seconds: int
    codex_session_name: str
    codex_event_poll_interval_seconds: float
    codex_event_poll_max_attempts: int
    codex_terminal_success_types: tuple[str, ...]
    codex_terminal_failure_types: tuple[str, ...]
    workspace_root_dir: Path
    workspace_base_branch: str
    workspace_branch_prefix: str
    workspace_cleanup_on_failure: bool
    workspace_max_workspaces: int
    validation_commands: list[list[str]]
    validation_profiles: dict[str, list[list[str]]]
    validation_default_profile: str
    validation_repo_profiles: dict[str, str]
    review_max_rounds: int
    review_required_reviewer_decision_fields: tuple[str, ...]
    guardrail_command_rules: list["CommandPolicyRule"]
    guardrail_file_rules: list["FilePolicyRule"]
    guardrail_runtime_observation_enabled: bool
    guardrail_approval_timeout_seconds: int
    trace_output_path: Path
    log_level: str
    logger_name: str


@dataclass(slots=True)
class SessionHandle:
    session_id: str
    request_id: str
    status: str
    created_at: datetime
    workspace_path: Path | None = None
    ended_at: datetime | None = None


@dataclass(slots=True)
class WorkspaceHandle:
    request_id: str
    repo_path: Path
    worktree_path: Path
    branch_name: str
    status: str


class WorkflowState(StrEnum):
    NEW = "new"
    DECOMPOSING = "decomposing"
    DECOMPOSED = "decomposed"
    CODING = "coding"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    NEEDS_FIX = "needs_fix"
    FAILED = "failed"


@dataclass(slots=True)
class TaskNode:
    id: str
    goal: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"


@dataclass(slots=True)
class TaskGraph:
    request_id: str
    tasks: list[TaskNode]

    def validate(self) -> None:
        if not self.tasks:
            raise ValueError("task graph must include at least one task")

        seen_ids: set[str] = set()
        task_ids = {task.id for task in self.tasks}
        for task in self.tasks:
            if not task.id.strip():
                raise ValueError("task id must not be empty")
            if task.id in seen_ids:
                raise ValueError(f"duplicate task id: {task.id}")
            if not task.goal.strip():
                raise ValueError(f"task goal must not be empty: {task.id}")
            missing = [dependency for dependency in task.depends_on if dependency not in task_ids]
            if missing:
                raise ValueError(f"task {task.id} depends on unknown task(s): {', '.join(missing)}")
            seen_ids.add(task.id)

        adjacency = {task.id: task.depends_on for task in self.tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise ValueError(f"task graph contains dependency cycle at: {node_id}")
            visiting.add(node_id)
            for dependency in adjacency[node_id]:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for task_id in adjacency:
            visit(task_id)


@dataclass(slots=True)
class ValidationResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    status: str


@dataclass(slots=True)
class ReviewDecision:
    decision: str
    summary: str
    findings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CommandPolicyRule:
    pattern: str
    action: str
    reason: str = ""


@dataclass(slots=True)
class FilePolicyRule:
    pattern: str
    action: str
    reason: str = ""


@dataclass(slots=True)
class GuardrailDecision:
    action: str
    reason: str
    matched_rule: str | None = None


@dataclass(slots=True)
class NormalizedEvent:
    event_id: str
    event_type: str
    session_id: str | None
    run_id: str | None
    task_id: str | None
    role: str | None
    status: str | None
    text: str | None
    summary: str | None
    decision: str | None
    tool_name: str | None
    tool_args: list[str] = field(default_factory=list)
    command_argv: list[str] = field(default_factory=list)
    tool_target: str | None = None
    raw_event: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservedAction:
    kind: str
    target: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowRun:
    request_id: str
    state: WorkflowState
    task_graph: TaskGraph | None = None
    current_task_id: str | None = None
    validation_results: list[ValidationResult] = field(default_factory=list)


@dataclass(slots=True)
class TaskExecutionResult:
    task_id: str
    status: str
    run_id: str
    terminal_event_type: str
    terminal_payload: dict[str, Any] = field(default_factory=dict)
    event_count: int = 0


@dataclass(slots=True)
class TraceEvent:
    request_id: str
    task_id: str | None
    session_id: str | None
    run_id: str | None
    agent_role: str
    status: str
    workflow_state: str | None
    correlation_id: str
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    validation_result: str | None = None
    normalized_event_type: str | None = None
    observed_action: dict[str, Any] | None = None
    guardrail_phase: str | None = None
    terminal_reason: str | None = None
    approval_status: str | None = None
    resume_from: str | None = None


@dataclass(slots=True)
class ApprovalRecord:
    request_id: str
    session_id: str | None
    workflow_state: str
    guardrail_phase: str | None
    action: str
    reason: str
    target: list[str] = field(default_factory=list)
    observed_action: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    status: str = "pending"


@dataclass(slots=True)
class ResumeResult:
    request_id: str
    status: str
    message: str
    approval_record: ApprovalRecord | None = None


@dataclass(slots=True)
class ReplayedWorkflow:
    request_id: str
    statuses: list[str] = field(default_factory=list)
    state_changes: list[dict[str, Any]] = field(default_factory=list)
    run_boundaries: list[dict[str, Any]] = field(default_factory=list)
    approval_boundaries: list[dict[str, Any]] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RunResult:
    request: HarnessRequest
    session: SessionHandle | None
    workspace: WorkspaceHandle | None
    status: str
    message: str
    task_graph: TaskGraph | None = None
    task_results: list[TaskExecutionResult] = field(default_factory=list)
    validation_results: list[ValidationResult] = field(default_factory=list)
    review_decisions: list[ReviewDecision] = field(default_factory=list)
    pending_approval: GuardrailDecision | None = None
    approval_record: ApprovalRecord | None = None
