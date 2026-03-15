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
from forgeflow_harness.cli import parse_constraints
from forgeflow_harness.config import load_config
from forgeflow_harness.models import HarnessConfig, HarnessRequest, TaskGraph, TaskNode
from forgeflow_harness.orchestrator import build_orchestrator
from forgeflow_harness.trace import TraceRepository


class FakeAdapter:
    def __init__(
        self,
        fail_create: bool = False,
        fail_run_on_task_id: str | None = None,
        terminal_event_type_by_task_id: dict[str, str] | None = None,
        include_event_ids: bool = True,
    ) -> None:
        self.fail_create = fail_create
        self.fail_run_on_task_id = fail_run_on_task_id
        self.terminal_event_type_by_task_id = terminal_event_type_by_task_id or {}
        self.include_event_ids = include_event_ids
        self.terminated_sessions: list[str] = []
        self.run_payloads: list[dict[str, object]] = []
        self.event_calls = 0

    def create_session(self, harness_request: HarnessRequest) -> str:
        if self.fail_create:
            raise CodexAdapterError("create failed")
        return f"session-{harness_request.request_id}"

    def start_run(self, session_id: str, input_payload: dict[str, object]) -> dict[str, str]:
        self.run_payloads.append(input_payload)
        task_id = input_payload.get("task_id")
        if task_id == self.fail_run_on_task_id:
            raise CodexAdapterError("run failed")
        return {"id": f"run-{task_id}", "session_id": session_id}

    def stream_events(self, session_id: str) -> dict[str, object]:
        self.event_calls += 1
        events: list[dict[str, object]] = []
        for index, payload in enumerate(self.run_payloads):
            task_id = str(payload["task_id"])
            run_id = f"run-{task_id}"
            event_type = self.terminal_event_type_by_task_id.get(task_id, "run_completed")
            event = {
                "type": event_type,
                "task_id": task_id,
                "run_id": run_id,
                "payload": {"task_id": task_id, "run_id": run_id},
            }
            if self.include_event_ids:
                event["id"] = f"evt-{index}-{task_id}"
            events.append(event)
        return {"events": events}

    def terminate_session(self, session_id: str) -> None:
        self.terminated_sessions.append(session_id)


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
        workspace_root_dir=tmp_path / "workspaces",
        workspace_base_branch="main",
        workspace_branch_prefix="ff",
        workspace_cleanup_on_failure=True,
        workspace_max_workspaces=10,
        validation_commands=commands,
        validation_profiles={"default": commands},
        validation_default_profile="default",
        validation_repo_profiles={},
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
            self.assertEqual(len(adapter.run_payloads), 3)
            self.assertEqual([payload["task_id"] for payload in adapter.run_payloads], ["T1", "T2", "T3"])
            self.assertEqual(result.validation_results[0].status, "passed")
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
                    "task_finished",
                    "task_started",
                    "run_started",
                    "task_finished",
                    "task_started",
                    "run_started",
                    "task_finished",
                    "workflow_state_changed",
                    "validation_started",
                    "validation_finished",
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


if __name__ == "__main__":
    unittest.main()
