from __future__ import annotations

from dataclasses import asdict

from forgeflow_harness.models import ApprovalRecord, ResumeResult, TraceEvent, utc_now
from forgeflow_harness.trace import TraceReplay, TraceRepository


class ApprovalController:
    def __init__(self, repository: TraceRepository) -> None:
        self._repository = repository
        self._replay = TraceReplay(repository)

    def resume(self, request_id: str, decision: str) -> ResumeResult:
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"approve", "reject", "expire"}:
            raise ValueError("decision must be approve, reject, or expire")

        pending_event = self._latest_pending_event(request_id)
        if pending_event is None:
            return ResumeResult(request_id=request_id, status="not_found", message="no pending approval found")

        approval_record = self._approval_record_from_event(pending_event)
        if normalized_decision == "approve":
            approval_record.status = "approved"
            status = "approved"
            message = f"approval recorded; rerun from {approval_record.workflow_state}"
        elif normalized_decision == "reject":
            approval_record.status = "rejected"
            status = "rejected"
            message = "approval rejected; workflow should terminate"
        else:
            approval_record.status = "expired"
            status = "expired"
            message = "approval expired; workflow should terminate"

        self._repository.append(
            TraceEvent(
                request_id=request_id,
                task_id=self._string_or_none(pending_event.get("task_id")),
                session_id=self._string_or_none(pending_event.get("session_id")),
                run_id=self._string_or_none(pending_event.get("run_id")),
                agent_role="orchestrator",
                status="approval_resolved",
                workflow_state=approval_record.workflow_state,
                correlation_id=self._correlation_id(pending_event),
                timestamp=utc_now(),
                payload={"approval_record": asdict(approval_record), "decision": normalized_decision},
                approval_status=approval_record.status,
                resume_from=approval_record.workflow_state if normalized_decision == "approve" else None,
                terminal_reason=None if normalized_decision == "approve" else f"approval_{approval_record.status}",
            )
        )
        return ResumeResult(
            request_id=request_id,
            status=status,
            message=message,
            approval_record=approval_record,
        )

    def rebuild(self, request_id: str):
        return self._replay.rebuild(request_id)

    def _latest_pending_event(self, request_id: str) -> dict[str, object] | None:
        events = self._repository.list_events(request_id)
        for event in reversed(events):
            if event.get("status") == "approval_pending" and event.get("approval_status") == "pending":
                return event
        return None

    def _approval_record_from_event(self, event: dict[str, object]) -> ApprovalRecord:
        payload = event.get("payload")
        decision = {}
        target: list[str] = []
        if isinstance(payload, dict):
            raw_decision = payload.get("decision")
            if isinstance(raw_decision, dict):
                decision = raw_decision
            raw_target = payload.get("target", [])
            if isinstance(raw_target, list):
                target = [item for item in raw_target if isinstance(item, str)]

        return ApprovalRecord(
            request_id=self._string_or_none(event.get("request_id")) or "",
            session_id=self._string_or_none(event.get("session_id")),
            workflow_state=self._string_or_none(event.get("workflow_state")) or "awaiting_approval",
            guardrail_phase=self._string_or_none(event.get("guardrail_phase")),
            action=self._string_or_none(decision.get("action")) or "approval_required",
            reason=self._string_or_none(decision.get("reason")) or "approval required",
            target=target,
            observed_action=event.get("observed_action") if isinstance(event.get("observed_action"), dict) else None,
            created_at=utc_now(),
            status="pending",
        )

    def _correlation_id(self, event: dict[str, object]) -> str:
        parts = [
            self._string_or_none(event.get("request_id")),
            self._string_or_none(event.get("task_id")),
            self._string_or_none(event.get("run_id")),
        ]
        return ":".join(part for part in parts if part)

    def _string_or_none(self, value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None
