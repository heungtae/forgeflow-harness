from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from forgeflow_harness.models import ReplayedWorkflow, TraceEvent


class TraceRepository:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TraceEvent) -> None:
        serializable = asdict(event)
        serializable["timestamp"] = event.timestamp.isoformat()
        with self.output_path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(serializable, sort_keys=True, default=self._json_default))
            file_obj.write("\n")

    def list_events(self, request_id: str | None = None) -> list[dict[str, object]]:
        if not self.output_path.exists():
            return []

        events: list[dict[str, object]] = []
        for line in self.output_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if request_id is None or event.get("request_id") == request_id:
                events.append(event)
        return events

    def _json_default(self, value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


class TraceReplay:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository

    def rebuild(self, request_id: str) -> ReplayedWorkflow:
        events = self._repository.list_events(request_id)
        events.sort(key=self._sort_key)

        replay = ReplayedWorkflow(request_id=request_id)
        for event in events:
            status = str(event.get("status", ""))
            replay.statuses.append(status)

            if status == "workflow_state_changed":
                replay.state_changes.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "from": self._payload_value(event, "from"),
                        "to": self._payload_value(event, "to"),
                    }
                )
            if status == "run_started":
                replay.run_boundaries.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "run_id": event.get("run_id"),
                        "task_id": event.get("task_id"),
                        "agent_role": self._payload_value(event, "agent_role"),
                    }
                )
            if status in {"approval_pending", "approval_resolved"}:
                replay.approval_boundaries.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "status": status,
                        "approval_status": event.get("approval_status"),
                        "resume_from": event.get("resume_from"),
                        "workflow_state": event.get("workflow_state"),
                    }
                )
            if status == "validation_finished":
                replay.validation_results.extend(self._payload_results(event))
        return replay

    def _sort_key(self, event: dict[str, object]) -> tuple[datetime, str]:
        timestamp = str(event.get("timestamp", ""))
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            parsed = datetime.min
        return parsed, str(event.get("status", ""))

    def _payload_value(self, event: dict[str, object], key: str) -> object:
        payload = event.get("payload")
        if isinstance(payload, dict):
            return payload.get(key)
        return None

    def _payload_results(self, event: dict[str, object]) -> list[dict[str, object]]:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return []
        results = payload.get("results", [])
        if isinstance(results, list):
            return [result for result in results if isinstance(result, dict)]
        return []
