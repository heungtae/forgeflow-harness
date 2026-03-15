from __future__ import annotations

import logging
from dataclasses import asdict

from forgeflow_harness.adapter import CodexAdapter, CodexAdapterError
from forgeflow_harness.models import (
    HarnessConfig,
    HarnessRequest,
    RunResult,
    SessionHandle,
    TaskGraph,
    TaskNode,
    TraceEvent,
    ValidationResult,
    WorkflowState,
    WorkspaceHandle,
    utc_now,
)
from forgeflow_harness.session import SessionManager
from forgeflow_harness.trace import TraceRepository
from forgeflow_harness.workspace import WorkspaceError, WorkspaceHarness


class HarnessOrchestrator:
    def __init__(
        self,
        config: HarnessConfig,
        logger: logging.Logger,
        trace_repository: TraceRepository,
        adapter: CodexAdapter,
    ) -> None:
        self._config = config
        self._logger = logger
        self._trace_repository = trace_repository
        self._adapter = adapter
        self._session_manager = SessionManager(adapter)
        self._workspace_harness = WorkspaceHarness(config)

    def run(self, harness_request: HarnessRequest) -> RunResult:
        session: SessionHandle | None = None
        workspace: WorkspaceHandle | None = None
        task_graph: TaskGraph | None = None
        validation_results: list[ValidationResult] = []
        state = WorkflowState.NEW

        self._emit_event(harness_request, "request_received", {})
        self._log("request received", harness_request, None, None, "started")

        try:
            harness_request.validate()
            self._emit_event(harness_request, "request_validated", {"repo": harness_request.repo})

            session = self._session_manager.create(harness_request)
            self._emit_event(harness_request, "session_created", {"session_id": session.session_id})
            self._log("session created", harness_request, session, None, "created")

            workspace = self._workspace_harness.prepare(harness_request)
            session.workspace_path = workspace.worktree_path
            self._emit_event(
                harness_request,
                "workspace_created",
                {"workspace_path": str(workspace.worktree_path), "branch_name": workspace.branch_name},
            )
            self._log("workspace created", harness_request, session, workspace, "ready")

            state = self._transition_state(harness_request, state, WorkflowState.DECOMPOSING)
            task_graph = self._decompose_request(harness_request)
            task_graph.validate()
            self._emit_event(
                harness_request,
                "task_graph_created",
                {"tasks": [self._serialize_task(task) for task in task_graph.tasks]},
            )

            state = self._transition_state(harness_request, state, WorkflowState.DECOMPOSED)
            state = self._transition_state(harness_request, state, WorkflowState.CODING)
            self._run_task_graph(harness_request, session, workspace, task_graph)

            state = self._transition_state(harness_request, state, WorkflowState.VALIDATING)
            self._emit_event(
                harness_request,
                "validation_started",
                {"commands": self._config.validation_commands},
            )
            validation_results = self._workspace_harness.run_validation(
                self._config.validation_commands,
                workspace.worktree_path,
            )
            self._emit_event(
                harness_request,
                "validation_finished",
                {"results": [self._serialize_validation_result(result) for result in validation_results]},
                validation_result="passed" if self._validation_succeeded(validation_results) else "failed",
            )

            if self._validation_succeeded(validation_results):
                state = self._transition_state(harness_request, state, WorkflowState.DONE)
                session.status = WorkflowState.DONE.value
                message = "task graph executed and validation passed"
            else:
                state = self._transition_state(harness_request, state, WorkflowState.NEEDS_FIX)
                session.status = WorkflowState.NEEDS_FIX.value
                message = "task graph executed but validation failed"

            return RunResult(
                request=harness_request,
                session=session,
                workspace=workspace,
                status=state.value,
                message=message,
                task_graph=task_graph,
                validation_results=validation_results,
            )
        except (ValueError, WorkspaceError, CodexAdapterError) as exc:
            state = WorkflowState.FAILED
            self._emit_event(harness_request, "request_failed", {"error": str(exc)}, validation_result="failed")
            self._log("request failed", harness_request, session, workspace, "failed")
            self._cleanup(harness_request, session, workspace)
            return RunResult(
                request=harness_request,
                session=session,
                workspace=workspace,
                status=state.value,
                message=str(exc),
                task_graph=task_graph,
                validation_results=validation_results,
            )

    def _cleanup(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle | None,
        workspace: WorkspaceHandle | None,
    ) -> None:
        self._emit_event(harness_request, "cleanup_started", {})
        if workspace is not None:
            self._workspace_harness.cleanup(workspace)
        if session is not None and session.status != "terminated":
            self._session_manager.terminate(session)
        self._emit_event(harness_request, "cleanup_finished", {})

    def _decompose_request(self, harness_request: HarnessRequest) -> TaskGraph:
        return TaskGraph(
            request_id=harness_request.request_id,
            tasks=[
                TaskNode(id="T1", goal=f"Analyze root cause and context for: {harness_request.goal}"),
                TaskNode(id="T2", goal=f"Implement the requested change for: {harness_request.goal}", depends_on=["T1"]),
                TaskNode(
                    id="T3",
                    goal=f"Add or update regression verification for: {harness_request.goal}",
                    depends_on=["T2"],
                ),
            ],
        )

    def _run_task_graph(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        task_graph: TaskGraph,
    ) -> None:
        for task in task_graph.tasks:
            task.status = "running"
            self._emit_event(
                harness_request,
                "task_started",
                {"task": self._serialize_task(task)},
                task_id=task.id,
            )
            self._adapter.start_run(
                session.session_id,
                {
                    "task_id": task.id,
                    "task_goal": task.goal,
                    "request_goal": harness_request.goal,
                    "repo": harness_request.repo,
                    "workspace_path": str(workspace.worktree_path),
                    "constraints": harness_request.constraints,
                },
            )
            task.status = "completed"
            self._emit_event(
                harness_request,
                "task_finished",
                {"task": self._serialize_task(task)},
                task_id=task.id,
            )

    def _transition_state(
        self,
        harness_request: HarnessRequest,
        previous: WorkflowState,
        next_state: WorkflowState,
    ) -> WorkflowState:
        self._emit_event(
            harness_request,
            "workflow_state_changed",
            {"from": previous.value, "to": next_state.value},
        )
        return next_state

    def _serialize_task(self, task: TaskNode) -> dict[str, object]:
        return {
            "id": task.id,
            "goal": task.goal,
            "depends_on": list(task.depends_on),
            "status": task.status,
        }

    def _serialize_validation_result(self, result: ValidationResult) -> dict[str, object]:
        return asdict(result)

    def _validation_succeeded(self, validation_results: list[ValidationResult]) -> bool:
        return bool(validation_results) and all(result.exit_code == 0 for result in validation_results)

    def _emit_event(
        self,
        harness_request: HarnessRequest,
        status: str,
        payload: dict[str, object],
        task_id: str | None = None,
        validation_result: str | None = None,
    ) -> None:
        event = TraceEvent(
            request_id=harness_request.request_id,
            task_id=task_id,
            agent_role="orchestrator",
            status=status,
            timestamp=utc_now(),
            payload=payload,
            changed_files=[],
            validation_result=validation_result,
        )
        self._trace_repository.append(event)

    def _log(
        self,
        message: str,
        harness_request: HarnessRequest,
        session: SessionHandle | None,
        workspace: WorkspaceHandle | None,
        status: str,
    ) -> None:
        self._logger.info(
            message,
            extra={
                "request_id": harness_request.request_id,
                "task_id": None,
                "agent_role": "orchestrator",
                "session_id": None if session is None else session.session_id,
                "workspace_path": None if workspace is None else str(workspace.worktree_path),
                "status": status,
            },
        )


def build_orchestrator(
    config: HarnessConfig,
    logger: logging.Logger,
    trace_repository: TraceRepository,
    adapter: CodexAdapter | None = None,
) -> HarnessOrchestrator:
    return HarnessOrchestrator(
        config=config,
        logger=logger,
        trace_repository=trace_repository,
        adapter=adapter or CodexAdapter(config),
    )
