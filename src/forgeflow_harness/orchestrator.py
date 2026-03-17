from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from forgeflow_harness.adapter import CodexAdapter, CodexAdapterError
from forgeflow_harness.guardrails import GuardrailEngine
from forgeflow_harness.models import (
    ApprovalRecord,
    GuardrailDecision,
    HarnessConfig,
    HarnessRequest,
    NormalizedEvent,
    ObservedAction,
    ReviewDecision,
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
from forgeflow_harness.normalizer import EventNormalizer
from forgeflow_harness.session import SessionManager
from forgeflow_harness.trace import TraceRepository
from forgeflow_harness.workspace import WorkspaceError, WorkspaceHarness


class ApprovalRequiredPause(RuntimeError):
    def __init__(self, decision: GuardrailDecision, approval_record: ApprovalRecord | None = None) -> None:
        super().__init__(decision.reason)
        self.decision = decision
        self.approval_record = approval_record


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
        self._guardrails = GuardrailEngine(config.guardrail_command_rules, config.guardrail_file_rules)
        self._event_normalizer = EventNormalizer()
        self._latest_approval_record: ApprovalRecord | None = None

    def run(self, harness_request: HarnessRequest) -> RunResult:
        session: SessionHandle | None = None
        workspace: WorkspaceHandle | None = None
        task_graph: TaskGraph | None = None
        task_results: list[TaskExecutionResult] = []
        validation_results: list[ValidationResult] = []
        review_decisions: list[ReviewDecision] = []
        pending_approval: GuardrailDecision | None = None
        approval_record: ApprovalRecord | None = None
        state = WorkflowState.NEW
        self._latest_approval_record = None

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
            state, validation_results, review_decisions, pending_approval = self._run_review_cycle(
                harness_request,
                session,
                workspace,
                state,
                task_graph,
            )
            session.status = state.value
            message = self._result_message(state, validation_results, pending_approval)
            approval_record = self._latest_approval_record

            return RunResult(
                request=harness_request,
                session=session,
                workspace=workspace,
                status=state.value,
                message=message,
                task_graph=task_graph,
                task_results=task_results,
                validation_results=validation_results,
                review_decisions=review_decisions,
                pending_approval=pending_approval,
                approval_record=approval_record,
            )
        except ApprovalRequiredPause as exc:
            state = WorkflowState.AWAITING_APPROVAL
            pending_approval = exc.decision
            if session is not None:
                session.status = state.value
                approval_record = exc.approval_record or self._latest_approval_record
            return RunResult(
                request=harness_request,
                session=session,
                workspace=workspace,
                status=state.value,
                message=self._result_message(state, validation_results, pending_approval),
                task_graph=task_graph,
                task_results=task_results,
                validation_results=validation_results,
                review_decisions=review_decisions,
                pending_approval=pending_approval,
                approval_record=approval_record,
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
                review_decisions=review_decisions,
                pending_approval=pending_approval,
                approval_record=approval_record,
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
                session_id=session.session_id,
                workflow_state=WorkflowState.CODING,
            )
            task_result = self._run_agent(
                harness_request,
                session,
                workspace,
                agent_role="coder",
                task_id=task.id,
                workflow_state=WorkflowState.CODING,
                input_payload={
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
                {
                    "task": self._serialize_task(task),
                    "run_id": task_result.run_id,
                    "terminal_event_type": task_result.terminal_event_type,
                    "event_count": task_result.event_count,
                },
                task_id=task.id,
                session_id=session.session_id,
                run_id=task_result.run_id,
                workflow_state=WorkflowState.CODING,
            )
            task_results.append(task_result)
        return task_results

    def _run_review_cycle(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        state: WorkflowState,
        task_graph: TaskGraph,
    ) -> tuple[WorkflowState, list[ValidationResult], list[ReviewDecision], GuardrailDecision | None]:
        review_decisions: list[ReviewDecision] = []
        validation_results: list[ValidationResult] = []
        latest_pending: GuardrailDecision | None = None
        current_state = state

        for round_index in range(self._config.review_max_rounds + 1):
            current_state = self._transition_state(harness_request, current_state, WorkflowState.VALIDATING)
            current_state, validation_results, latest_pending = self._run_validation(
                harness_request,
                session,
                workspace,
                current_state,
            )
            if current_state in {WorkflowState.AWAITING_APPROVAL, WorkflowState.FAILED, WorkflowState.NEEDS_FIX}:
                return current_state, validation_results, review_decisions, latest_pending

            current_state = self._transition_state(harness_request, current_state, WorkflowState.REVIEWING)
            review_decision = self._run_reviewer(harness_request, session, workspace, task_graph, validation_results, round_index)
            review_decisions.append(review_decision)
            if review_decision.decision == "pass":
                current_state = self._transition_state(harness_request, current_state, WorkflowState.DONE)
                return current_state, validation_results, review_decisions, latest_pending

            if review_decision.decision == "blocked":
                pending = GuardrailDecision(action="approval_required", reason=review_decision.summary, matched_rule=None)
                current_state = self._transition_state(harness_request, current_state, WorkflowState.AWAITING_APPROVAL)
                self._emit_pending_approval(harness_request, session, current_state, pending, None, guardrail_phase="runtime")
                return current_state, validation_results, review_decisions, pending

            if round_index >= self._config.review_max_rounds:
                self._emit_event(
                    harness_request,
                    "review_round_limit_reached",
                    {"round": round_index + 1, "max_rounds": self._config.review_max_rounds},
                    session_id=session.session_id,
                    workflow_state=current_state,
                )
                current_state = self._transition_state(harness_request, current_state, WorkflowState.FAILED)
                return current_state, validation_results, review_decisions, latest_pending

            current_state = self._transition_state(harness_request, current_state, WorkflowState.FIXING)
            self._run_fixer(harness_request, session, workspace, task_graph, review_decision, round_index)

        current_state = self._transition_state(harness_request, current_state, WorkflowState.FAILED)
        return current_state, validation_results, review_decisions, latest_pending

    def _run_validation(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        state: WorkflowState,
    ) -> tuple[WorkflowState, list[ValidationResult], GuardrailDecision | None]:
        changed_files = self._workspace_harness.list_changed_files(workspace.worktree_path)
        pending = self._check_file_guardrails(harness_request, session, state, changed_files)
        if pending is not None:
            return WorkflowState.AWAITING_APPROVAL, [], pending

        validation_profile = self._select_validation_profile(harness_request, workspace.repo_path)
        validation_commands = self._config.validation_profiles[validation_profile]
        for command in validation_commands:
            pending = self._check_command_guardrails(harness_request, session, state, command)
            if pending is not None:
                return WorkflowState.AWAITING_APPROVAL, [], pending

        self._emit_event(
            harness_request,
            "validation_started",
            {"profile_name": validation_profile, "commands": validation_commands},
            session_id=session.session_id,
            workflow_state=state,
            changed_files=changed_files,
        )
        validation_results = self._workspace_harness.run_validation(
            validation_commands,
            workspace.worktree_path,
        )
        self._emit_event(
            harness_request,
            "validation_finished",
            {"results": [self._serialize_validation_result(result) for result in validation_results]},
            session_id=session.session_id,
            workflow_state=state,
            validation_result="passed" if self._validation_succeeded(validation_results) else "failed",
            changed_files=changed_files,
        )
        if self._validation_succeeded(validation_results):
            return state, validation_results, None
        return WorkflowState.NEEDS_FIX, validation_results, None

    def _run_reviewer(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        task_graph: TaskGraph,
        validation_results: list[ValidationResult],
        round_index: int,
    ) -> ReviewDecision:
        changed_files = self._workspace_harness.list_changed_files(workspace.worktree_path)
        self._emit_event(
            harness_request,
            "review_started",
            {"round": round_index + 1, "task_count": len(task_graph.tasks)},
            session_id=session.session_id,
            workflow_state=WorkflowState.REVIEWING,
            changed_files=changed_files,
        )
        task_result = self._run_agent(
            harness_request,
            session,
            workspace,
            agent_role="reviewer",
            task_id=None,
            workflow_state=WorkflowState.REVIEWING,
            input_payload={
                "role": "reviewer",
                "request_id": harness_request.request_id,
                "request_goal": harness_request.goal,
                "workspace_path": str(workspace.worktree_path),
                "changed_files": changed_files,
                "task_graph": [self._serialize_task(task) for task in task_graph.tasks],
                "validation_results": [self._serialize_validation_result(result) for result in validation_results],
                "round": round_index + 1,
            },
        )
        try:
            review_decision = self._extract_review_decision(task_result.terminal_payload)
        except CodexAdapterError as exc:
            self._emit_event(
                harness_request,
                "decision_parse_failed",
                {"error": str(exc), "terminal_payload": task_result.terminal_payload},
                session_id=session.session_id,
                run_id=task_result.run_id,
                workflow_state=WorkflowState.REVIEWING,
                changed_files=changed_files,
                terminal_reason="decision_parse_failed",
            )
            raise
        self._emit_event(
            harness_request,
            "review_finished",
            {"decision": asdict(review_decision), "round": round_index + 1},
            session_id=session.session_id,
            run_id=task_result.run_id,
            workflow_state=WorkflowState.REVIEWING,
            changed_files=changed_files,
        )
        return review_decision

    def _run_fixer(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        task_graph: TaskGraph,
        review_decision: ReviewDecision,
        round_index: int,
    ) -> None:
        changed_files = self._workspace_harness.list_changed_files(workspace.worktree_path)
        self._emit_event(
            harness_request,
            "fix_started",
            {"round": round_index + 1, "findings": review_decision.findings},
            session_id=session.session_id,
            workflow_state=WorkflowState.FIXING,
            changed_files=changed_files,
        )
        task_result = self._run_agent(
            harness_request,
            session,
            workspace,
            agent_role="fixer",
            task_id=None,
            workflow_state=WorkflowState.FIXING,
            input_payload={
                "role": "fixer",
                "request_id": harness_request.request_id,
                "request_goal": harness_request.goal,
                "workspace_path": str(workspace.worktree_path),
                "changed_files": changed_files,
                "task_graph": [self._serialize_task(task) for task in task_graph.tasks],
                "review_decision": asdict(review_decision),
                "round": round_index + 1,
            },
        )
        self._emit_event(
            harness_request,
            "fix_finished",
            {"round": round_index + 1, "run_id": task_result.run_id},
            session_id=session.session_id,
            run_id=task_result.run_id,
            workflow_state=WorkflowState.FIXING,
            changed_files=self._workspace_harness.list_changed_files(workspace.worktree_path),
        )

    def _run_agent(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        agent_role: str,
        task_id: str | None,
        workflow_state: WorkflowState,
        input_payload: dict[str, object],
    ) -> TaskExecutionResult:
        run_response = self._adapter.start_run(
            session.session_id,
            {"role": agent_role, **input_payload},
        )
        run_id = self._extract_run_id(run_response)
        self._emit_event(
            harness_request,
            "run_started",
            {"task_id": task_id, "run_id": run_id, "agent_role": agent_role},
            task_id=task_id,
            session_id=session.session_id,
            run_id=run_id,
            workflow_state=workflow_state,
            changed_files=self._workspace_harness.list_changed_files(workspace.worktree_path),
        )
        return self._wait_for_task_terminal_event(
            harness_request,
            session,
            workspace,
            task_id,
            run_id,
            agent_role,
            workflow_state,
        )

    def _extract_run_id(self, run_response: dict[str, object]) -> str:
        run_id = self._extract_first_str(run_response, ["id"], ["run_id"], ["run", "id"])
        if run_id is None:
            raise CodexAdapterError("Codex run response did not include run id")
        return run_id

    def _wait_for_task_terminal_event(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workspace: WorkspaceHandle,
        task_id: str | None,
        run_id: str,
        agent_role: str,
        workflow_state: WorkflowState,
    ) -> TaskExecutionResult:
        seen_event_ids: set[str] = set()
        matched_event_count = 0

        for _ in range(self._config.codex_event_poll_max_attempts):
            for event in self._event_normalizer.normalize_events(self._adapter.stream_events(session.session_id)):
                if event.event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event.event_id)

                if not self._event_matches_task(event, task_id, run_id, agent_role):
                    continue

                matched_event_count += 1
                observed_action = self._extract_observed_action(event)
                self._emit_event(
                    harness_request,
                    "agent_event_received",
                    {
                        "event_type": event.event_type,
                        "agent_role": agent_role,
                        "raw_event": event.raw_event,
                    },
                    task_id=task_id,
                    session_id=session.session_id,
                    run_id=run_id,
                    workflow_state=workflow_state,
                    normalized_event_type=event.event_type,
                    observed_action=observed_action,
                )
                if observed_action is not None:
                    self._check_runtime_observed_action(
                        harness_request,
                        session,
                        workflow_state,
                        observed_action,
                    )

                is_terminal, terminal_status = self._classify_terminal_event(event)
                if not is_terminal:
                    continue
                if terminal_status == "failed":
                    raise CodexAdapterError(
                        f"task {task_id or agent_role} failed with event {event.event_type}"
                    )
                return TaskExecutionResult(
                    task_id="" if task_id is None else task_id,
                    status="completed",
                    run_id=run_id,
                    terminal_event_type=event.event_type,
                    terminal_payload=event.raw_event,
                    event_count=matched_event_count,
                )

            if self._config.codex_event_poll_interval_seconds > 0:
                time.sleep(self._config.codex_event_poll_interval_seconds)

        raise CodexAdapterError(f"task {task_id or agent_role} timed out waiting for terminal event")

    def _extract_first_str(self, payload: dict[str, object], *paths: list[str]) -> str | None:
        for path in paths:
            value = self._extract_path(payload, path)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_string_list(self, payload: dict[str, object], *paths: list[str]) -> list[str]:
        for path in paths:
            value = self._extract_path(payload, path)
            if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
                return [item for item in value]
        return []

    def _extract_path(self, payload: dict[str, object], path: list[str]) -> object:
        current: object = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _event_matches_task(self, event: NormalizedEvent, task_id: str | None, run_id: str, agent_role: str) -> bool:
        if event.run_id is not None:
            return event.run_id == run_id
        if task_id is not None and event.task_id is not None:
            return event.task_id == task_id
        if task_id is None and event.role is not None:
            return event.role == agent_role
        return False

    def _classify_terminal_event(self, event: NormalizedEvent) -> tuple[bool, str]:
        candidates = {event.event_type}
        if event.status is not None:
            candidates.add(event.status)
        if any(candidate in self._config.codex_terminal_failure_types for candidate in candidates):
            return True, "failed"
        if any(candidate in self._config.codex_terminal_success_types for candidate in candidates):
            return True, "completed"
        return False, "running"

    def _extract_observed_action(self, event: NormalizedEvent) -> ObservedAction | None:
        if not self._config.guardrail_runtime_observation_enabled:
            return None

        command_argv = event.command_argv or event.tool_args
        if command_argv:
            return ObservedAction(
                kind="command",
                target=" ".join(command_argv),
                details={"tool_name": event.tool_name or "command", "event_type": event.event_type},
            )

        tool_name = (event.tool_name or "").lower()
        if event.tool_target is None:
            return None
        if tool_name in {"write_file", "edit_file"}:
            return ObservedAction(kind="file_write", target=event.tool_target, details={"event_type": event.event_type})
        if tool_name in {"delete_file", "remove_file"}:
            return ObservedAction(kind="file_delete", target=event.tool_target, details={"event_type": event.event_type})
        return None

    def _check_runtime_observed_action(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workflow_state: WorkflowState,
        observed_action: ObservedAction,
    ) -> None:
        if observed_action.kind == "command":
            decision = self._guardrails.check_command(observed_action.target.split())
        elif observed_action.kind in {"file_write", "file_delete"}:
            decision = self._guardrails.check_files([observed_action.target])
        else:
            return

        self._emit_event(
            harness_request,
            "guardrail_checked",
            {"kind": observed_action.kind, "decision": asdict(decision), "targets": [observed_action.target]},
            session_id=session.session_id,
            workflow_state=workflow_state,
            changed_files=[observed_action.target] if observed_action.kind.startswith("file") else [],
            observed_action=observed_action,
            guardrail_phase="runtime",
        )
        if decision.action == "deny":
            raise WorkspaceError(f"guardrail denied runtime {observed_action.kind}: {decision.reason}")
        if decision.action == "approval_required":
            self._emit_pending_approval(
                harness_request,
                session,
                workflow_state,
                decision,
                [observed_action.target],
                observed_action=observed_action,
                guardrail_phase="runtime",
            )
            raise ApprovalRequiredPause(decision, self._latest_approval_record)

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
        session_id: str | None = None,
        run_id: str | None = None,
        workflow_state: WorkflowState | None = None,
        changed_files: list[str] | None = None,
        validation_result: str | None = None,
        normalized_event_type: str | None = None,
        observed_action: ObservedAction | None = None,
        guardrail_phase: str | None = None,
        terminal_reason: str | None = None,
        approval_status: str | None = None,
        resume_from: str | None = None,
    ) -> None:
        event = TraceEvent(
            request_id=harness_request.request_id,
            task_id=task_id,
            session_id=session_id,
            run_id=run_id,
            agent_role="orchestrator",
            status=status,
            workflow_state=None if workflow_state is None else workflow_state.value,
            correlation_id=self._correlation_id(harness_request.request_id, task_id, run_id),
            timestamp=utc_now(),
            payload=payload,
            changed_files=[] if changed_files is None else changed_files,
            validation_result=validation_result,
            normalized_event_type=normalized_event_type,
            observed_action=None if observed_action is None else asdict(observed_action),
            guardrail_phase=guardrail_phase,
            terminal_reason=terminal_reason,
            approval_status=approval_status,
            resume_from=resume_from,
        )
        self._trace_repository.append(event)

    def _check_file_guardrails(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workflow_state: WorkflowState,
        changed_files: list[str],
    ) -> GuardrailDecision | None:
        decision = self._guardrails.check_files(changed_files)
        self._emit_event(
            harness_request,
            "guardrail_checked",
            {"kind": "file", "decision": asdict(decision), "targets": changed_files},
            session_id=session.session_id,
            workflow_state=workflow_state,
            changed_files=changed_files,
            guardrail_phase="preflight",
        )
        if decision.action == "deny":
            raise WorkspaceError(f"guardrail denied changed file access: {decision.reason}")
        if decision.action == "approval_required":
            self._emit_pending_approval(
                harness_request,
                session,
                workflow_state,
                decision,
                changed_files,
                guardrail_phase="preflight",
            )
            return decision
        return None

    def _check_command_guardrails(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workflow_state: WorkflowState,
        command: list[str],
    ) -> GuardrailDecision | None:
        decision = self._guardrails.check_command(command)
        self._emit_event(
            harness_request,
            "guardrail_checked",
            {"kind": "command", "decision": asdict(decision), "targets": [" ".join(command)]},
            session_id=session.session_id,
            workflow_state=workflow_state,
            guardrail_phase="preflight",
        )
        if decision.action == "deny":
            raise WorkspaceError(f"guardrail denied command: {decision.reason}")
        if decision.action == "approval_required":
            self._emit_pending_approval(
                harness_request,
                session,
                workflow_state,
                decision,
                command,
                guardrail_phase="preflight",
            )
            return decision
        return None

    def _emit_pending_approval(
        self,
        harness_request: HarnessRequest,
        session: SessionHandle,
        workflow_state: WorkflowState,
        decision: GuardrailDecision,
        target: list[str] | None,
        observed_action: ObservedAction | None = None,
        guardrail_phase: str | None = None,
    ) -> None:
        approval_record = self._approval_record(session, workflow_state, decision, target, observed_action, guardrail_phase)
        self._latest_approval_record = approval_record
        self._emit_event(
            harness_request,
            "approval_pending",
            {
                "decision": asdict(decision),
                "target": [] if target is None else target,
                "approval_record": asdict(approval_record),
            },
            session_id=session.session_id,
            workflow_state=workflow_state,
            changed_files=[] if target is None else target,
            observed_action=observed_action,
            guardrail_phase=guardrail_phase,
            approval_status="pending",
        )

    def _extract_review_decision(self, terminal_payload: dict[str, Any]) -> ReviewDecision:
        normalized = self._event_normalizer.normalize(terminal_payload)
        raw_decision = normalized.decision
        summary = normalized.summary
        missing_fields = self._missing_reviewer_fields(raw_decision, summary)
        if missing_fields:
            raise CodexAdapterError(
                f"reviewer terminal event missing required field(s): {', '.join(missing_fields)}"
            )

        decision_map = {
            "pass": "pass",
            "approved": "pass",
            "fix_required": "fix_required",
            "changes_requested": "fix_required",
            "blocked": "blocked",
        }
        decision = decision_map.get(raw_decision.lower())
        if decision is None:
            raise CodexAdapterError(f"unknown review decision: {raw_decision}")

        findings = self._extract_string_list(terminal_payload, ["payload", "findings"], ["findings"])
        suggested_actions = self._extract_string_list(
            terminal_payload,
            ["payload", "suggested_actions"],
            ["suggested_actions"],
        )
        return ReviewDecision(
            decision=decision,
            summary=summary or f"review decision: {decision}",
            findings=findings,
            suggested_actions=suggested_actions,
        )

    def _missing_reviewer_fields(self, raw_decision: str | None, summary: str | None) -> list[str]:
        missing: list[str] = []
        for field_spec in self._config.review_required_reviewer_decision_fields:
            aliases = [alias.strip() for alias in field_spec.split("|") if alias.strip()]
            if any(alias in {"review_decision", "decision", "result"} for alias in aliases):
                if raw_decision is None:
                    missing.append(field_spec)
                continue
            if "summary" in aliases and summary is None:
                missing.append(field_spec)
        return missing

    def _approval_record(
        self,
        session: SessionHandle,
        workflow_state: WorkflowState,
        decision: GuardrailDecision,
        target: list[str] | None,
        observed_action: ObservedAction | None,
        guardrail_phase: str | None,
    ) -> ApprovalRecord:
        created_at = utc_now()
        return ApprovalRecord(
            request_id=session.request_id,
            session_id=session.session_id,
            workflow_state=workflow_state.value,
            guardrail_phase=guardrail_phase,
            action=decision.action,
            reason=decision.reason,
            target=[] if target is None else target,
            observed_action=None if observed_action is None else asdict(observed_action),
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self._config.guardrail_approval_timeout_seconds),
            status="pending",
        )

    def _result_message(
        self,
        state: WorkflowState,
        validation_results: list[ValidationResult],
        pending_approval: GuardrailDecision | None,
    ) -> str:
        if state == WorkflowState.DONE:
            return "task graph executed, validation passed, and review completed"
        if state == WorkflowState.AWAITING_APPROVAL and pending_approval is not None:
            return f"workflow paused awaiting approval: {pending_approval.reason}"
        if state == WorkflowState.NEEDS_FIX:
            if validation_results:
                return "task graph executed but validation failed"
            return "workflow requires additional fixes"
        return "workflow failed"

    def _correlation_id(self, request_id: str, task_id: str | None, run_id: str | None) -> str:
        return ":".join(part for part in [request_id, task_id, run_id] if part)

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
