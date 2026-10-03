from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from .event_bus import BusEvent, MissionEventBus
from .event_journal import StructuredEventJournal, _safe_value
from .kernel_contracts import EventKind


def _verification_evidence(result: Any) -> dict[str, Any]:
    """Only explicit, structured tool evidence can produce a proof event."""
    if not bool(getattr(result, "success", False)):
        return {}
    detail = getattr(result, "detail", "")
    if not isinstance(detail, str) or len(detail) > 65536:
        return {}
    try:
        payload = json.loads(detail or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("verified") is not True:
        return {}
    # A target name or the word "verified" is not an observed state.
    return {
        key: payload[key] for key in (
            "value", "value_length", "after", "observed_state", "evidence",
            "proof", "visible_tabs", "window_closed_as_last_tab",
        ) if key in payload and payload[key] is not None
        and (payload[key] or (type(payload[key]) in (int, float) and payload[key] == 0))
    }


class TracingToolRegistry:
    """Transparent existing tool proxy with optional journal and live observers."""

    def __init__(
        self, delegate: Any, *,
        journal: StructuredEventJournal | None = None,
        event_bus: MissionEventBus | None = None,
    ):
        self._delegate = delegate
        self.journal = journal
        self.event_bus = event_bus
        self._local = threading.local()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    @property
    def knowledge(self):
        return getattr(self._delegate, "knowledge", None)

    def set_mission(self, mission_id: str | None, *, agent_id: str | None = None) -> None:
        self._local.mission_id = mission_id
        self._local.agent_id = agent_id

    def record(
        self, kind: EventKind, payload: dict[str, Any], *,
        component: str = "interaction_runtime", success: bool | None = None,
        parent_event_id: str | None = None,
    ) -> str | None:
        mission_id = getattr(self._local, "mission_id", None)
        if not mission_id:
            return None
        event_id = f"e_{uuid.uuid4().hex}"
        safe_payload = _safe_value(payload)
        agent_id = getattr(self._local, "agent_id", None)
        if self.journal is not None:
            try:
                self.journal.append_event(
                    mission_id=mission_id, kind=kind, event_id=event_id,
                    agent_id=agent_id, component=component, success=success,
                    parent_event_id=parent_event_id, payload=safe_payload,
                )
            except Exception:
                # A journal failure must not prevent the real action.
                pass
        if self.event_bus is not None:
            self.event_bus.publish(BusEvent(
                kind=kind.value, mission_id=mission_id, agent_id=agent_id,
                component=component, payload=safe_payload, event_id=event_id,
                parent_event_id=parent_event_id, success=success,
                created_at=time.time(),
            ))
        return event_id

    def execute(self, name: str, arguments: dict[str, Any], *, approved: bool = False):
        request_id = self.record(
            EventKind.TOOL_REQUESTED,
            {"tool_name": str(name), "arguments": dict(arguments or {}),
             "approved": bool(approved)}, component="native_tools",
        )
        started = time.perf_counter()
        try:
            result = self._delegate.execute(name, arguments, approved=approved)
        except Exception as exc:
            self.record(
                EventKind.TOOL_RESULT,
                {"tool_name": str(name), "error": str(exc),
                 "error_type": type(exc).__name__, "verification_status": "unverified",
                 "duration_ms": (time.perf_counter() - started) * 1000},
                component="native_tools", success=False, parent_event_id=request_id,
            )
            raise
        evidence = _verification_evidence(result)
        result_id = self.record(
            EventKind.TOOL_RESULT,
            {"tool_name": str(name), "message": str(getattr(result, "message", "") or ""),
             "detail": str(getattr(result, "detail", "") or ""),
             "end_session": bool(getattr(result, "end_session", False)),
             "should_exit": bool(getattr(result, "should_exit", False)),
             "verification_status": "verified" if evidence else "unverified",
             "duration_ms": (time.perf_counter() - started) * 1000},
            component="native_tools", success=bool(getattr(result, "success", False)),
            parent_event_id=request_id,
        )
        if evidence:
            self.record(
                EventKind.PROOF,
                {"tool_name": str(name), "verified": True, "evidence": evidence,
                 "source": "tool_result", "result_event_id": result_id},
                component="verification", success=True, parent_event_id=request_id,
            )
        return result


class StructuredTracingRuntime:
    """Passive runtime wrapper; a finished turn is not proof of a mission."""

    def __init__(
        self, delegate: Any, tools: TracingToolRegistry, *,
        journal: StructuredEventJournal | None = None,
        owner_agent_id: str = "interaction",
        configured_provider: str = "", configured_model: str = "",
    ):
        self.delegate = delegate
        self.tools = tools
        self.journal = journal or tools.journal
        self.event_bus = tools.event_bus
        self.owner_agent_id = owner_agent_id
        self.configured_provider = configured_provider
        self.configured_model = configured_model

    def reset(self) -> None:
        self.delegate.reset()

    def warm_up(self, *, log=None) -> None:
        self.delegate.warm_up(log=log)

    def _finish_journal(self, mission_id: str, *, success: bool, summary: str) -> None:
        if self.journal is not None:
            try:
                # Retain legacy journal semantics, but do not publish this as
                # semantic mission completion to live UI consumers.
                self.journal.finish_mission(
                    mission_id, success=success, summary=summary[:1200],
                    agent_id=self.owner_agent_id,
                )
            except Exception:
                pass

    def run(self, user_text: str, *, log=None, phase=None):
        mission_id = f"t_{uuid.uuid4().hex}"
        if self.journal is not None:
            try:
                mission_id = self.journal.create_mission(
                    goal_summary=str(user_text or "")[:600],
                    owner_agent_id=self.owner_agent_id,
                )
            except Exception:
                pass
        self.tools.set_mission(mission_id, agent_id=self.owner_agent_id)
        self.tools.record(EventKind.TURN_STARTED, {
            "source": "agent_runtime", "configured_provider": self.configured_provider,
            "configured_model": self.configured_model,
        })
        self.tools.record(EventKind.USER_INPUT, {"text": str(user_text or "")[:2400]})

        def observed_phase(value: str) -> None:
            self.tools.record(EventKind.RUNTIME_PHASE, {"phase": str(value)})
            if phase is not None:
                phase(value)

        started = time.perf_counter()
        try:
            try:
                result = self.delegate.run(user_text, log=log, phase=observed_phase)
            except Exception as exc:
                self.tools.record(EventKind.LLM_RESULT, {"error": str(exc)}, success=False)
                self.tools.record(EventKind.TURN_FINISHED, {
                    "outcome": "error", "error_type": type(exc).__name__,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                }, success=False)
                self._finish_journal(mission_id, success=False, summary=str(exc))
                raise
            actions = tuple(getattr(result, "actions", ()) or ())
            failures = sum(not bool(getattr(action, "success", False)) for action in actions)
            summary = str(getattr(result, "text", "") or "")
            self.tools.record(EventKind.LLM_RESULT, {
                "response_text": summary[:2400], "action_count": len(actions),
                "failed_action_count": failures,
                "end_session": bool(getattr(result, "end_session", False)),
                "should_exit": bool(getattr(result, "should_exit", False)),
            }, success=not bool(failures))
            self.tools.record(EventKind.TURN_FINISHED, {
                "outcome": "returned", "action_count": len(actions),
                "failed_action_count": failures,
                "duration_ms": (time.perf_counter() - started) * 1000,
            })
            self._finish_journal(mission_id, success=not bool(failures), summary=summary)
            return result
        finally:
            self.tools.set_mission(None)
