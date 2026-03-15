from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path

from forgeflow_harness.adapter import CodexAdapter, CodexAdapterError
from forgeflow_harness.models import (
    HarnessConfig,
    HarnessRequest,
    RunResult,
    SessionHandle,
    TaskGraph,
    TaskExecutionResult,
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
        task_results: list[TaskExecutionResult] = []
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
            task_results = self._run_task_graph(harness_request, session, workspace, task_graph)

            state = self._transition_state(harness_request, state, WorkflowState.VALIDATING)
            validation_profile = self._select_validation_profile(harness_request, workspace.repo_path)
            validation_commands = self._config.validation_profiles[validation_profile]
            self._emit_event(
                harness_request,
                "validation_started",
                {"profile_name": validation_profile, "commands": validation_commands},
            )
            validation_results = self._workspace_harness.run_validation(
                validation_commands,
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
                task_results=task_results,
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
                task_results=task_results,
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
    ) -> list[TaskExecutionResult]:
        task_results: list[TaskExecutionResult] = []
        for task in task_graph.tasks:
            task.status = "running"
            self._emit_event(
                harness_request,
                "task_started",
                {"task": self._serialize_task(task)},
                task_id=task.id,
            )
            run_response = self._adapter.start_run(
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
            run_id = self._extract_run_id(run_response)
            self._emit_event(
                harness_request,
                "run_started",
                {"task_id": task.id, "run_id": run_id},
                task_id=task.id,
            )
            task_result = self._wait_for_task_terminal_event(harness_request, session.session_id, task.id, run_id)
            task.status = "completed"
            self._emit_event(
                harness_request,
                "task_finished",
                {
                    "task": self._serialize_task(task),
                    "run_id": task_result.run_id,
                    "terminal_event_type": task_result.terminal_event_type,
                    "event_count": task_result.event_count,
                },
                task_id=task.id,
            )
            task_results.append(task_result)
        return task_results

    def _extract_run_id(self, run_response: dict[str, object]) -> str:
        run_id = run_response.get("id")
        if not isinstance(run_id, str) or not run_id:
            raise CodexAdapterError("Codex run response did not include run id")
        return run_id

    def _wait_for_task_terminal_event(
        self,
        harness_request: HarnessRequest,
        session_id: str,
        task_id: str,
        run_id: str,
    ) -> TaskExecutionResult:
        seen_event_ids: set[str] = set()
        matched_event_count = 0

        for _ in range(self._config.codex_event_poll_max_attempts):
            response = self._adapter.stream_events(session_id)
            events = self._extract_events(response)
            for index, event in enumerate(events):
                event_id = self._event_id(event, index)
                if event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)

                if not self._event_matches_task(event, task_id, run_id):
                    continue

                matched_event_count += 1
                is_terminal, terminal_status = self._classify_terminal_event(event)
                if not is_terminal:
                    continue
                if terminal_status == "failed":
                    raise CodexAdapterError(
                        f"task {task_id} failed with event {self._event_type(event)}"
                    )
                return TaskExecutionResult(
                    task_id=task_id,
                    status="completed",
                    run_id=run_id,
                    terminal_event_type=self._event_type(event),
                    terminal_payload=event,
                    event_count=matched_event_count,
                )

            if self._config.codex_event_poll_interval_seconds > 0:
                time.sleep(self._config.codex_event_poll_interval_seconds)

        raise CodexAdapterError(f"task {task_id} timed out waiting for terminal event")

    def _extract_events(self, response: object) -> list[dict[str, object]]:
        if isinstance(response, list):
            return [event for event in response if isinstance(event, dict)]
        if isinstance(response, dict):
            raw_events = response.get("events", [])
            if isinstance(raw_events, list):
                return [event for event in raw_events if isinstance(event, dict)]
        return []

    def _event_id(self, event: dict[str, object], index: int) -> str:
        event_id = event.get("id")
        if isinstance(event_id, str) and event_id:
            return event_id
        return f"{index}:{self._event_type(event)}"

    def _event_matches_task(self, event: dict[str, object], task_id: str, run_id: str) -> bool:
        payload = event.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}

        event_task_id = event.get("task_id") or payload.get("task_id")
        event_run_id = event.get("run_id") or payload.get("run_id")

        if isinstance(event_task_id, str) and event_task_id and event_task_id != task_id:
            return False
        if isinstance(event_run_id, str) and event_run_id and event_run_id != run_id:
            return False
        return True

    def _classify_terminal_event(self, event: dict[str, object]) -> tuple[bool, str]:
        event_type = self._event_type(event)
        if any(token in event_type for token in ("failed", "error")):
            return True, "failed"
        if any(token in event_type for token in ("completed", "succeeded", "success")):
            return True, "completed"
        return False, "running"

    def _event_type(self, event: dict[str, object]) -> str:
        for key in ("type", "status", "event"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value.lower()
        return "unknown"

    def _select_validation_profile(self, harness_request: HarnessRequest, repo_path: Path) -> str:
        requested_profile = harness_request.constraints.get("validation_profile")
        if isinstance(requested_profile, str) and requested_profile:
            if requested_profile not in self._config.validation_profiles:
                raise ValueError(f"unknown validation profile: {requested_profile}")
            return requested_profile

        repo_name = repo_path.name
        mapped_profile = self._config.validation_repo_profiles.get(repo_name)
        if mapped_profile is not None:
            return mapped_profile
        return self._config.validation_default_profile

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
