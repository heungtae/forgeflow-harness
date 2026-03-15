from __future__ import annotations

from forgeflow_harness.adapter import CodexAdapter
from forgeflow_harness.models import HarnessRequest, SessionHandle, utc_now


class SessionManager:
    def __init__(self, adapter: CodexAdapter) -> None:
        self._adapter = adapter

    def create(self, harness_request: HarnessRequest) -> SessionHandle:
        session_id = self._adapter.create_session(harness_request)
        return SessionHandle(
            session_id=session_id,
            request_id=harness_request.request_id,
            status="created",
            created_at=utc_now(),
        )

    def terminate(self, session: SessionHandle) -> SessionHandle:
        self._adapter.terminate_session(session.session_id)
        session.status = "terminated"
        session.ended_at = utc_now()
        return session
