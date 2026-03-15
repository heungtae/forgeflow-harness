from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from forgeflow_harness.models import HarnessConfig, HarnessRequest


class CodexAdapterError(RuntimeError):
    """Raised when Codex App Server interaction fails."""


class CodexAdapter:
    def __init__(self, config: HarnessConfig) -> None:
        self._base_url = config.codex_base_url.rstrip("/")
        self._timeout_seconds = config.codex_timeout_seconds
        self._session_name = config.codex_session_name

    def create_session(self, harness_request: HarnessRequest) -> str:
        payload = {
            "name": self._session_name,
            "metadata": {"request_id": harness_request.request_id},
        }
        data = self._post("/sessions", payload)
        session_id = data.get("id")
        if not session_id:
            raise CodexAdapterError("Codex response did not include session id")
        return str(session_id)

    def start_run(self, session_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        payload = {"input": input_payload}
        return self._post(f"/sessions/{session_id}/run", payload)

    def stream_events(self, session_id: str) -> dict[str, Any]:
        return self._get(f"/sessions/{session_id}/events")

    def terminate_session(self, session_id: str) -> None:
        self._post(f"/sessions/{session_id}/terminate", {})

    def _get(self, path: str) -> dict[str, Any]:
        req = request.Request(f"{self._base_url}{path}", method="GET")
        return self._send(req)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(req)

    def _send(self, req: request.Request) -> dict[str, Any]:
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except error.URLError as exc:
            raise CodexAdapterError(str(exc)) from exc
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise CodexAdapterError("Codex response was not valid JSON") from exc
