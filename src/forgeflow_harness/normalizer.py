from __future__ import annotations

from forgeflow_harness.models import NormalizedEvent


class EventNormalizer:
    def normalize_events(self, response: object) -> list[NormalizedEvent]:
        events = self._extract_events(response)
        return [self.normalize(event, index) for index, event in enumerate(events)]

    def normalize(self, event: dict[str, object], index: int = 0) -> NormalizedEvent:
        event_type = (
            self._extract_first_str(event, ["type"], ["status"], ["event"], ["payload", "type"], ["payload", "status"])
            or "unknown"
        ).lower()
        status = self._extract_first_str(event, ["status"], ["payload", "status"])
        tool_args = self._extract_string_list(
            event,
            ["tool_args"],
            ["payload", "tool_args"],
            ["payload", "tool", "args"],
        )
        command_argv = self._extract_string_list(
            event,
            ["command_argv"],
            ["payload", "command", "argv"],
            ["payload", "command", "args"],
            ["payload", "argv"],
        )
        return NormalizedEvent(
            event_id=self._extract_first_str(event, ["id"]) or f"{index}:{event_type}",
            event_type=event_type,
            session_id=self._extract_first_str(event, ["session_id"], ["payload", "session_id"]),
            run_id=self._extract_first_str(event, ["run_id"], ["payload", "run_id"], ["payload", "run", "id"]),
            task_id=self._extract_first_str(event, ["task_id"], ["payload", "task_id"], ["payload", "task", "id"]),
            role=self._extract_first_str(
                event,
                ["role"],
                ["agent_role"],
                ["payload", "role"],
                ["payload", "agent_role"],
            ),
            status=None if status is None else status.lower(),
            text=self._extract_first_str(event, ["message"], ["payload", "message"]),
            summary=self._extract_first_str(event, ["summary"], ["payload", "summary"], ["payload", "result", "summary"]),
            decision=self._extract_first_str(
                event,
                ["review_decision"],
                ["decision"],
                ["result"],
                ["payload", "review_decision"],
                ["payload", "decision"],
                ["payload", "result"],
                ["payload", "result", "decision"],
            ),
            tool_name=self._extract_first_str(
                event,
                ["tool_name"],
                ["payload", "tool_name"],
                ["payload", "tool", "name"],
                ["payload", "name"],
            ),
            tool_args=tool_args,
            command_argv=command_argv,
            tool_target=self._extract_first_str(
                event,
                ["file_path"],
                ["payload", "file_path"],
                ["payload", "path"],
                ["payload", "target"],
            ),
            raw_event=event,
        )

    def _extract_events(self, response: object) -> list[dict[str, object]]:
        if isinstance(response, list):
            return [event for event in response if isinstance(event, dict)]
        if isinstance(response, dict):
            raw_events = response.get("events", [])
            if isinstance(raw_events, list):
                return [event for event in raw_events if isinstance(event, dict)]
        return []

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
