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
    workspace_root_dir: Path
    workspace_base_branch: str
    workspace_branch_prefix: str
    workspace_cleanup_on_failure: bool
    workspace_max_workspaces: int
    validation_commands: list[list[str]]
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
class WorkflowRun:
    request_id: str
    state: WorkflowState
    task_graph: TaskGraph | None = None
    current_task_id: str | None = None
    validation_results: list[ValidationResult] = field(default_factory=list)


@dataclass(slots=True)
class TraceEvent:
    request_id: str
    task_id: str | None
    agent_role: str
    status: str
    timestamp: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    validation_result: str | None = None


@dataclass(slots=True)
class RunResult:
    request: HarnessRequest
    session: SessionHandle | None
    workspace: WorkspaceHandle | None
    status: str
    message: str
    task_graph: TaskGraph | None = None
    validation_results: list[ValidationResult] = field(default_factory=list)
