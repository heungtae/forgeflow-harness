from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from forgeflow_harness.adapter import CodexAdapterError
from forgeflow_harness.approvals import ApprovalController
from forgeflow_harness.cli import parse_constraints
from forgeflow_harness.config import load_config
from forgeflow_harness.models import CommandPolicyRule, FilePolicyRule, HarnessConfig, HarnessRequest, TaskGraph, TaskNode
from forgeflow_harness.orchestrator import build_orchestrator
from forgeflow_harness.trace import TraceReplay, TraceRepository


class FakeAdapter:
    def __init__(
        self,
        fail_create: bool = False,
        fail_run_on_task_id: str | None = None,
        terminal_event_type_by_task_id: dict[str, str] | None = None,
        include_event_ids: bool = True,
        review_decisions: list[str] | None = None,
        write_files_by_role: dict[str, list[str]] | None = None,
        event_payload_shape_by_role: dict[str, str] | None = None,
        observed_actions_by_role: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self.fail_create = fail_create
        self.fail_run_on_task_id = fail_run_on_task_id
        self.terminal_event_type_by_task_id = terminal_event_type_by_task_id or {}
        self.include_event_ids = include_event_ids
        self.review_decisions = review_decisions or []
        self.write_files_by_role = write_files_by_role or {}
        self.event_payload_shape_by_role = event_payload_shape_by_role or {}
        self.observed_actions_by_role = observed_actions_by_role or {}
        self.terminated_sessions: list[str] = []
        self.run_payloads: list[dict[str, object]] = []
        self.event_calls = 0
        self.reviewer_runs = 0
        self.fixer_runs = 0

    def create_session(self, harness_request: HarnessRequest) -> str:
        if self.fail_create:
            raise CodexAdapterError("create failed")
        return f"session-{harness_request.request_id}"

    def start_run(self, session_id: str, input_payload: dict[str, object]) -> dict[str, str]:
        self.run_payloads.append(input_payload)
        role = str(input_payload.get("role", "coder"))
        if role == "reviewer":
            self.reviewer_runs += 1
        if role == "fixer":
            self.fixer_runs += 1
        workspace_path = input_payload.get("workspace_path")
        if isinstance(workspace_path, str):
            self._write_files(role, Path(workspace_path))
        task_id = input_payload.get("task_id")
        if self.fail_run_on_task_id is not None and task_id == self.fail_run_on_task_id:
            raise CodexAdapterError("run failed")
        if role in {"reviewer", "fixer"}:
            return {"id": f"run-{role}-{len(self.run_payloads)}", "session_id": session_id}
        return {"id": f"run-{task_id}", "session_id": session_id}

    def stream_events(self, session_id: str) -> dict[str, object]:
        self.event_calls += 1
        events: list[dict[str, object]] = []
        for index, payload in enumerate(self.run_payloads):
            role = str(payload.get("role", "coder"))
            task_id = payload.get("task_id")
            run_id = f"run-{role}-{index + 1}" if role in {"reviewer", "fixer"} else f"run-{task_id}"
            for action_index, action in enumerate(self.observed_actions_by_role.get(role, [])):
                observed_event = {
                    "type": str(action.get("event_type", "tool_called")),
                    "run_id": run_id,
                    "payload": dict(action),
                }
                if "role" not in observed_event["payload"]:
                    observed_event["payload"]["role"] = role
                if task_id is not None:
                    observed_event["task_id"] = str(task_id)
                if self.include_event_ids:
                    observed_event["id"] = f"evt-observed-{index}-{action_index}-{run_id}"
                events.append(observed_event)
            if role in {"reviewer", "fixer"}:
                event_type = "run_completed"
                event_payload: dict[str, object] = {"run_id": run_id}
                if role == "reviewer":
                    decision_index = min(self.reviewer_runs - 1, len(self.review_decisions) - 1)
                    review_decision = self.review_decisions[decision_index] if self.review_decisions else "pass"
                    event_payload.update(
                        {
                            "review_decision": review_decision,
                            "summary": f"review decision: {review_decision}",
                            "findings": ["address reviewer finding"] if review_decision == "fix_required" else [],
                            "suggested_actions": ["run fixer"] if review_decision == "fix_required" else [],
                        }
                    )
                event = self._shape_terminal_event(role, task_id, run_id, event_type, event_payload)
            else:
                task_id = str(payload["task_id"])
                event_type = self.terminal_event_type_by_task_id.get(task_id, "run_completed")
                event = self._shape_terminal_event(role, task_id, run_id, event_type, {"task_id": task_id, "run_id": run_id})
            events.append(event)
        return {"events": events}

    def terminate_session(self, session_id: str) -> None:
        self.terminated_sessions.append(session_id)

    def _write_files(self, role: str, workspace_path: Path) -> None:
        for relative_path in self.write_files_by_role.get(role, []):
            target = workspace_path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"generated by {role}\n", encoding="utf-8")

    def _shape_terminal_event(
        self,
        role: str,
        task_id: object,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        shape = self.event_payload_shape_by_role.get(role, "default")
        if shape == "nested":
            event: dict[str, object] = {
                "status": event_type,
                "payload": {"run": {"id": run_id}, **payload},
            }
            if task_id is not None and role == "coder":
                event["payload"]["task"] = {"id": str(task_id)}
        elif shape == "result_nested":
            nested_payload = dict(payload)
            decision = nested_payload.pop("review_decision", None)
            summary = nested_payload.pop("summary", None)
            event = {
                "type": event_type,
                "run_id": run_id,
                "payload": {"result": {"decision": decision, "summary": summary}, **nested_payload},
            }
        elif shape == "decision_alias":
            alias_payload = dict(payload)
            review_decision = alias_payload.pop("review_decision", None)
            if review_decision is not None:
                alias_payload["decision"] = review_decision
            event = {"type": event_type, "run_id": run_id, "payload": alias_payload}
            if task_id is not None and role == "coder":
                event["task_id"] = str(task_id)
        elif shape == "role_only":
            event = {"type": event_type, "payload": {"role": role, **payload}}
            if task_id is not None and role == "coder":
                event["task_id"] = str(task_id)
        elif shape == "decision_only":
            decision_payload = dict(payload)
            decision_payload.pop("summary", None)
            event = {"type": event_type, "run_id": run_id, "payload": decision_payload}
        else:
            event = {"type": event_type, "run_id": run_id, "payload": payload}
            if task_id is not None and role == "coder":
                event["task_id"] = str(task_id)
        event.setdefault("role", role)
        if self.include_event_ids:
            event["id"] = f"evt-{role}-{run_id}"
        return event


class FakeLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, object]]] = []

    def info(self, message: str, extra: dict[str, object]) -> None:
        self.messages.append((message, extra))


def make_config(tmp_path: Path, validation_commands: list[list[str]] | None = None) -> HarnessConfig:
    commands = validation_commands or [["python3", "-c", "print('validation ok')"]]
    return HarnessConfig(
        codex_base_url="http://127.0.0.1:8000",
        codex_timeout_seconds=30,
        codex_session_name="test",
        codex_event_poll_interval_seconds=0.0,
        codex_event_poll_max_attempts=3,
        codex_terminal_success_types=("run_completed", "task_completed", "completed"),
        codex_terminal_failure_types=("run_failed", "task_failed", "failed", "error"),
        workspace_root_dir=tmp_path / "workspaces",
        workspace_base_branch="main",
        workspace_branch_prefix="ff",
        workspace_cleanup_on_failure=True,
        workspace_max_workspaces=10,
        validation_commands=commands,
        validation_profiles={"default": commands},
        validation_default_profile="default",
        validation_repo_profiles={},
        review_max_rounds=2,
        review_required_reviewer_decision_fields=("review_decision|decision|result", "summary"),
        guardrail_command_rules=[],
        guardrail_file_rules=[],
        guardrail_runtime_observation_enabled=True,
        guardrail_approval_timeout_seconds=86400,
        trace_output_path=tmp_path / "trace.jsonl",
        log_level="INFO",
        logger_name="forgeflow_harness",
    )


def init_git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)


def read_trace_events(trace_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]


class HarnessTests(unittest.TestCase):
    def test_parse_constraints_coerces_bool_and_int(self) -> None:
        constraints = parse_constraints(["allow_network=false", "retries=3", "mode=safe"])
        self.assertEqual(constraints, {"allow_network": False, "retries": 3, "mode": "safe"})

    def test_load_config_reads_validation_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config_path = tmp_path / "config.toml"
            config_path.write_text(
                """
[codex]
base_url = "http://127.0.0.1:8000"
timeout_seconds = 30
session_name = "forgeflow-week2"
event_poll_interval_seconds = 0.5
event_poll_max_attempts = 10
terminal_success_types = ["run_completed", "completed"]
terminal_failure_types = ["run_failed", "failed"]

[workspace]
root_dir = ".forgeflow/workspaces"
base_branch = "main"
branch_prefix = "ff"
cleanup_on_failure = true
max_workspaces = 10

[validation]
commands = [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]]

[trace]
output_path = ".forgeflow/traces/trace.jsonl"

[logging]
level = "INFO"
logger_name = "forgeflow_harness"
""".strip(),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(
                config.validation_commands,
                [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]],
            )
            self.assertEqual(config.validation_profiles["default"], config.validation_commands)
            self.assertEqual(config.validation_default_profile, "default")
            self.assertEqual(config.review_max_rounds, 2)
            self.assertEqual(
                config.review_required_reviewer_decision_fields,
                ("review_decision|decision|result", "summary"),
            )
            self.assertEqual(config.codex_terminal_success_types, ("run_completed", "completed"))
            self.assertEqual(config.codex_terminal_failure_types, ("run_failed", "failed"))
            self.assertTrue(config.guardrail_runtime_observation_enabled)
            self.assertEqual(config.guardrail_approval_timeout_seconds, 86400)

    def test_load_config_reads_validation_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config_path = tmp_path / "config.toml"
            config_path.write_text(
                """
[codex]
base_url = "http://127.0.0.1:8000"
timeout_seconds = 30
session_name = "forgeflow-week2"
event_poll_interval_seconds = 1.0
event_poll_max_attempts = 30
terminal_success_types = ["run_completed", "task_completed", "completed"]
terminal_failure_types = ["run_failed", "task_failed", "failed", "error"]

[workspace]
root_dir = ".forgeflow/workspaces"
base_branch = "main"
branch_prefix = "ff"
cleanup_on_failure = true
max_workspaces = 10

[validation]
default_profile = "python-unittest"

[validation.profiles.python-unittest]
commands = [["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]]

[validation.profiles.fast-check]
commands = [["python3", "-c", "print('fast')"]]

[validation.repo_profiles]
forgeflow-harness = "fast-check"

[review]
max_rounds = 3
required_reviewer_decision_fields = ["review_decision|decision|result", "summary"]

[guardrail]
command_rules = [{ pattern = "python3 -m unittest *", action = "allow", reason = "default tests" }]
file_rules = [{ pattern = "db/migration/*", action = "approval_required", reason = "migration review" }]
runtime_observation_enabled = false
approval_timeout_seconds = 120

[trace]
output_path = ".forgeflow/traces/trace.jsonl"

[logging]
level = "INFO"
logger_name = "forgeflow_harness"
""".strip(),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.validation_default_profile, "python-unittest")
            self.assertEqual(config.validation_repo_profiles, {"forgeflow-harness": "fast-check"})
            self.assertEqual(config.validation_profiles["fast-check"], [["python3", "-c", "print('fast')"]])
            self.assertEqual(config.review_max_rounds, 3)
            self.assertEqual(
                config.review_required_reviewer_decision_fields,
                ("review_decision|decision|result", "summary"),
            )
            self.assertEqual(config.guardrail_command_rules[0].pattern, "python3 -m unittest *")
            self.assertEqual(config.guardrail_file_rules[0].action, "approval_required")
            self.assertFalse(config.guardrail_runtime_observation_enabled)
            self.assertEqual(config.guardrail_approval_timeout_seconds, 120)

    def test_task_graph_validate_rejects_cycle(self) -> None:
        task_graph = TaskGraph(
            request_id="REQ-CYCLE",
            tasks=[
                TaskNode(id="T1", goal="one", depends_on=["T2"]),
                TaskNode(id="T2", goal="two", depends_on=["T1"]),
            ],
        )

        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            task_graph.validate()

    def test_orchestrator_runs_three_tasks_and_finishes_done(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-001", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "done")
            self.assertIsNotNone(result.task_graph)
            self.assertEqual([task.id for task in result.task_graph.tasks], ["T1", "T2", "T3"])
            self.assertEqual(len(adapter.run_payloads), 4)
            self.assertEqual([payload.get("task_id") for payload in adapter.run_payloads[:3]], ["T1", "T2", "T3"])
            self.assertEqual(adapter.reviewer_runs, 1)
            self.assertEqual(result.validation_results[0].status, "passed")
            self.assertEqual(result.review_decisions[0].decision, "pass")
            self.assertTrue(result.workspace.worktree_path.exists())
            self.assertEqual(
                [event["status"] for event in read_trace_events(config.trace_output_path)],
                [
                    "request_received",
                    "request_validated",
                    "session_created",
                    "workspace_created",
                    "workflow_state_changed",
                    "task_graph_created",
                    "workflow_state_changed",
                    "workflow_state_changed",
                    "task_started",
                    "run_started",
                    "agent_event_received",
                    "task_finished",
                    "task_started",
                    "run_started",
                    "agent_event_received",
                    "task_finished",
                    "task_started",
                    "run_started",
                    "agent_event_received",
                    "task_finished",
                    "workflow_state_changed",
                    "guardrail_checked",
                    "guardrail_checked",
                    "validation_started",
                    "validation_finished",
                    "workflow_state_changed",
                    "review_started",
                    "run_started",
                    "agent_event_received",
                    "review_finished",
                    "workflow_state_changed",
                ],
            )
            self.assertGreaterEqual(adapter.event_calls, 3)

    def test_orchestrator_returns_needs_fix_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path, validation_commands=[["python3", "-c", "import sys; sys.exit(2)"]])
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-002", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "needs_fix")
            self.assertEqual(result.validation_results[0].exit_code, 2)
            self.assertEqual(result.review_decisions, [])
            self.assertTrue(result.workspace.worktree_path.exists())
            self.assertEqual(adapter.terminated_sessions, [])

    def test_orchestrator_cleans_up_when_task_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(fail_run_on_task_id="T2")
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-003", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "failed")
            self.assertIsNotNone(result.workspace)
            self.assertFalse(result.workspace.worktree_path.exists())
            self.assertEqual(adapter.terminated_sessions, ["session-REQ-003"])
            self.assertEqual(
                [event["status"] for event in read_trace_events(config.trace_output_path)][-3:],
                ["request_failed", "cleanup_started", "cleanup_finished"],
            )

    def test_orchestrator_fails_when_terminal_error_event_received(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(terminal_event_type_by_task_id={"T2": "run_failed"})
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-ERR", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "failed")
            self.assertFalse(result.workspace.worktree_path.exists())

    def test_orchestrator_fails_when_event_polling_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(terminal_event_type_by_task_id={"T1": "run_progress"})
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-TIMEOUT", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("timed out", result.message)

    def test_orchestrator_rejects_invalid_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(HarnessRequest(request_id="", repo="", goal="", constraints={}))

            self.assertEqual(result.status, "failed")
            self.assertIn("missing required fields", result.message)
            self.assertEqual(
                [event["status"] for event in read_trace_events(config.trace_output_path)],
                [
                    "request_received",
                    "request_failed",
                    "cleanup_started",
                    "cleanup_finished",
                ],
            )

    def test_trace_payload_includes_validation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            orchestrator.run(
                HarnessRequest(request_id="REQ-004", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            validation_event = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "validation_finished"][0]
            result = validation_event["payload"]["results"][0]
            self.assertEqual(result["command"], ["python3", "-c", "print('validation ok')"])
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["status"], "passed")

    def test_trace_payload_includes_run_id_and_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            orchestrator.run(
                HarnessRequest(request_id="REQ-RUN", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            task_finished = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "task_finished"][0]
            self.assertEqual(task_finished["payload"]["run_id"], "run-T1")
            self.assertEqual(task_finished["payload"]["terminal_event_type"], "run_completed")

    def test_orchestrator_runs_fixer_when_reviewer_requests_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(review_decisions=["fix_required", "pass"])
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-FIX", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "done")
            self.assertEqual([decision.decision for decision in result.review_decisions], ["fix_required", "pass"])
            self.assertEqual(adapter.fixer_runs, 1)
            statuses = [event["status"] for event in read_trace_events(config.trace_output_path)]
            self.assertIn("fix_started", statuses)
            self.assertIn("fix_finished", statuses)

    def test_orchestrator_pauses_when_guardrail_requires_file_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.guardrail_file_rules = [
                FilePolicyRule(pattern="db/migration/*", action="approval_required", reason="migration review")
            ]
            logger = FakeLogger()
            adapter = FakeAdapter(write_files_by_role={"coder": ["db/migration/V1__init.sql"]})
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-APPROVAL", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "awaiting_approval")
            self.assertIsNotNone(result.pending_approval)
            self.assertEqual(result.pending_approval.action, "approval_required")
            self.assertEqual(adapter.terminated_sessions, [])
            approval_event = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "approval_pending"][0]
            self.assertEqual(approval_event["payload"]["decision"]["reason"], "migration review")

    def test_orchestrator_fails_when_guardrail_denies_validation_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.guardrail_command_rules = [
                CommandPolicyRule(pattern="python3 -c *", action="deny", reason="inline python disabled")
            ]
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-DENY", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("guardrail denied command", result.message)

    def test_trace_events_include_correlation_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            orchestrator.run(
                HarnessRequest(request_id="REQ-TRACE", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            run_started = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "run_started"][0]
            self.assertEqual(run_started["session_id"], "session-REQ-TRACE")
            self.assertEqual(run_started["run_id"], "run-T1")
            self.assertEqual(run_started["workflow_state"], "coding")
            self.assertEqual(run_started["correlation_id"], "REQ-TRACE:T1:run-T1")

    def test_orchestrator_accepts_nested_terminal_event_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(event_payload_shape_by_role={"coder": "nested", "reviewer": "nested"})
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-NESTED", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "done")
            self.assertEqual(result.review_decisions[0].decision, "pass")

    def test_orchestrator_accepts_result_nested_reviewer_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(
                review_decisions=["approved"],
                event_payload_shape_by_role={"reviewer": "result_nested"},
            )
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-RESULT-NESTED", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "done")
            self.assertEqual(result.review_decisions[0].decision, "pass")

    def test_orchestrator_maps_reviewer_decision_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(
                review_decisions=["approved"],
                event_payload_shape_by_role={"reviewer": "decision_alias"},
            )
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-ALIAS", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "done")
            self.assertEqual(result.review_decisions[0].decision, "pass")

    def test_orchestrator_matches_reviewer_event_by_role_when_run_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(event_payload_shape_by_role={"reviewer": "role_only"})
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-ROLE-FALLBACK", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "done")
            self.assertEqual(result.review_decisions[0].decision, "pass")

    def test_orchestrator_fails_when_reviewer_summary_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            logger = FakeLogger()
            adapter = FakeAdapter(event_payload_shape_by_role={"reviewer": "decision_only"})
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-MISSING-SUMMARY", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("missing required field(s): summary", result.message)
            parse_failed = [
                event for event in read_trace_events(config.trace_output_path) if event["status"] == "decision_parse_failed"
            ][0]
            self.assertEqual(parse_failed["terminal_reason"], "decision_parse_failed")

    def test_orchestrator_pauses_on_runtime_observed_command_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.guardrail_command_rules = [
                CommandPolicyRule(pattern="rm -rf *", action="approval_required", reason="dangerous cleanup"),
            ]
            logger = FakeLogger()
            adapter = FakeAdapter(
                observed_actions_by_role={
                    "coder": [{"tool_name": "shell", "tool_args": ["rm", "-rf", "build"]}],
                }
            )
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-RUNTIME-APPROVAL", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "awaiting_approval")
            self.assertIsNotNone(result.approval_record)
            self.assertEqual(result.approval_record.guardrail_phase, "runtime")
            approval_event = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "approval_pending"][0]
            self.assertEqual(approval_event["guardrail_phase"], "runtime")
            self.assertEqual(approval_event["observed_action"]["kind"], "command")
            self.assertEqual(approval_event["approval_status"], "pending")

    def test_orchestrator_fails_on_runtime_observed_file_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.guardrail_file_rules = [
                FilePolicyRule(pattern=".env*", action="deny", reason="secret files blocked"),
            ]
            logger = FakeLogger()
            adapter = FakeAdapter(
                observed_actions_by_role={
                    "coder": [{"tool_name": "write_file", "file_path": ".env.local"}],
                }
            )
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-RUNTIME-DENY", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("guardrail denied runtime file_write", result.message)

    def test_trace_events_include_normalized_event_and_guardrail_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.guardrail_command_rules = [
                CommandPolicyRule(pattern="rm -rf *", action="approval_required", reason="dangerous cleanup"),
            ]
            logger = FakeLogger()
            adapter = FakeAdapter(
                observed_actions_by_role={
                    "coder": [{"tool_name": "shell", "tool_args": ["rm", "-rf", "build"]}],
                }
            )
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            orchestrator.run(
                HarnessRequest(request_id="REQ-TRACE-RUNTIME", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            agent_event = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "agent_event_received"][0]
            guardrail_event = [event for event in read_trace_events(config.trace_output_path) if event["guardrail_phase"] == "runtime"][0]
            self.assertEqual(agent_event["normalized_event_type"], "tool_called")
            self.assertEqual(agent_event["observed_action"]["target"], "rm -rf build")
            self.assertEqual(guardrail_event["guardrail_phase"], "runtime")

    def test_orchestrator_selects_validation_profile_from_constraint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.validation_profiles["fast"] = [["python3", "-c", "print('fast profile')"]]
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            orchestrator.run(
                HarnessRequest(
                    request_id="REQ-PROFILE",
                    repo=str(repo_path),
                    goal="Prepare coding session",
                    constraints={"validation_profile": "fast"},
                )
            )

            validation_started = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "validation_started"][0]
            self.assertEqual(validation_started["payload"]["profile_name"], "fast")

    def test_orchestrator_selects_validation_profile_from_repo_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.validation_profiles["repo-profile"] = [["python3", "-c", "print('repo profile')"]]
            config.validation_repo_profiles["repo"] = "repo-profile"
            logger = FakeLogger()
            adapter = FakeAdapter()
            orchestrator = build_orchestrator(config, logger, TraceRepository(config.trace_output_path), adapter=adapter)

            orchestrator.run(
                HarnessRequest(request_id="REQ-REPO", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )

            validation_started = [event for event in read_trace_events(config.trace_output_path) if event["status"] == "validation_started"][0]
            self.assertEqual(validation_started["payload"]["profile_name"], "repo-profile")

    def test_approval_controller_records_resolution_and_trace_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            repo_path = tmp_path / "repo"
            init_git_repo(repo_path)
            config = make_config(tmp_path)
            config.guardrail_file_rules = [
                FilePolicyRule(pattern="db/migration/*", action="approval_required", reason="migration review")
            ]
            logger = FakeLogger()
            repository = TraceRepository(config.trace_output_path)
            adapter = FakeAdapter(write_files_by_role={"coder": ["db/migration/V1__init.sql"]})
            orchestrator = build_orchestrator(config, logger, repository, adapter=adapter)

            result = orchestrator.run(
                HarnessRequest(request_id="REQ-RESUME", repo=str(repo_path), goal="Prepare coding session", constraints={})
            )
            self.assertEqual(result.status, "awaiting_approval")

            controller = ApprovalController(repository)
            resume_result = controller.resume("REQ-RESUME", "approve")

            self.assertEqual(resume_result.status, "approved")
            self.assertEqual(resume_result.approval_record.status, "approved")

            replay = TraceReplay(repository).rebuild("REQ-RESUME")
            self.assertIn("approval_pending", replay.statuses)
            self.assertIn("approval_resolved", replay.statuses)
            self.assertEqual(replay.approval_boundaries[-1]["approval_status"], "approved")
            self.assertEqual(replay.approval_boundaries[-1]["resume_from"], "validating")


if __name__ == "__main__":
    unittest.main()
