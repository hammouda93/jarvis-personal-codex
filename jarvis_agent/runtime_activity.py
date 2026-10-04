from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .event_bus import BusEvent
from .kernel_contracts import EventKind


@dataclass
class ObservedToolCall:
    request_id: str
    name: str
    status: str = "running"
    duration_ms: float | None = None
    result_event_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class RuntimeActivityState:
    """Bounded projection of one live turn, never a semantic mission verdict."""

    def __init__(self, *, max_calls: int = 100):
        self.max_calls = max(1, min(int(max_calls), 500))
        self.turn_id = ""
        self.status = "idle"
        self.configured_provider = ""
        self.configured_model = ""
        self.failed_action_count = 0
        self.dropped_calls = 0
        self.calls: OrderedDict[str, ObservedToolCall] = OrderedDict()

    def apply(self, event: BusEvent) -> bool:
        payload = event.payload
        if event.kind == EventKind.TURN_STARTED.value:
            self.turn_id = event.mission_id
            self.status = "running"
            self.configured_provider = str(payload.get("configured_provider") or "")[:120]
            self.configured_model = str(payload.get("configured_model") or "")[:120]
            self.failed_action_count = 0
            self.dropped_calls = 0
            self.calls.clear()
            return True
        if not self.turn_id or event.mission_id != self.turn_id:
            return False
        if event.kind == EventKind.RUNTIME_PHASE.value:
            if self.status in {"finished", "error"}:
                return False
            phase = str(payload.get("phase") or "")
            if phase in {"thinking", "acting"}:
                self.status = phase
                return True
        if event.kind == EventKind.TOOL_REQUESTED.value and event.event_id:
            if event.event_id in self.calls:
                return False
            self.calls[event.event_id] = ObservedToolCall(
                request_id=event.event_id, name=str(payload.get("tool_name") or "")[:120],
            )
            while len(self.calls) > self.max_calls:
                self.calls.popitem(last=False)
                self.dropped_calls += 1
            return True
        call = self.calls.get(event.parent_event_id or "")
        if event.kind == EventKind.TOOL_RESULT.value and call is not None:
            if call.status != "running" or not event.event_id:
                return False
            call.status = "completed" if event.success is True else "failed"
            call.result_event_id = event.event_id
            duration = payload.get("duration_ms")
            if type(duration) in (int, float) and math.isfinite(duration) and duration >= 0:
                call.duration_ms = float(duration)
            return True
        if event.kind == EventKind.PROOF.value and call is not None:
            evidence = payload.get("evidence")
            if (call.status == "completed" and event.success is True
                    and payload.get("verified") is True
                    and payload.get("source") == "tool_result"
                    and payload.get("result_event_id") == call.result_event_id
                    and isinstance(evidence, dict) and evidence):
                call.status = "verified"
                call.evidence = dict(evidence)
                return True
        if event.kind == EventKind.TURN_FINISHED.value:
            self.status = "error" if payload.get("outcome") == "error" else "finished"
            count = payload.get("failed_action_count", 0)
            self.failed_action_count = count if type(count) is int and count >= 0 else 0
            return True
        return False
