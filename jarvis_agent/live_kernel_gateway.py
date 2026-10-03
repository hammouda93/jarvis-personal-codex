from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .capability_registry import CapabilityRegistry, DEFAULT_CAPABILITY_REGISTRY
from .event_bus import BusEvent, MissionEventBus
from .kernel_contracts import EventKind, KernelRequest, RiskLevel, SyscallKind
from .kernel_policy import KernelPolicy
from .native_tools import AgentActionResult


@dataclass(frozen=True)
class LiveCapabilityRoute:
    tool_name: str
    agent_id: str
    capability: str
    syscall_kind: SyscallKind = SyscallKind.TOOL


_TOOL_ROUTES: dict[str, tuple[str, str, SyscallKind]] = {}


def _register(
    names: tuple[str, ...],
    agent_id: str,
    capability: str,
    kind: SyscallKind = SyscallKind.TOOL,
) -> None:
    for name in names:
        _TOOL_ROUTES[name] = (agent_id, capability, kind)


_register(
    ("list_windows", "inspect_active_window", "ground_ui_role", "observe_screen"),
    "windows", "computer.observe", SyscallKind.OBSERVATION,
)
_register(
    ("open_application", "open_file", "open_folder"),
    "windows", "computer.files",
)
_register(
    (
        "activate_window", "click_ui_element", "write_ui_element",
        "type_text_active_window", "press_key", "close_tab", "close_window",
        "click_visual_target", "write_visual_target",
    ),
    "windows", "computer.interact",
)
_register(("open_url",), "browser", "browser.navigate")
_register(("search_web",), "browser", "browser.search")
_register(("research_web",), "research", "research.web")
_register(
    (
        "msf_capabilities", "msf_describe_schema", "msf_count_records",
        "msf_query_records", "msf_readonly_sql", "msf_search_code",
        "msf_list_routes", "msf_resolve_route",
    ),
    "ms_football", "msf.read",
)
_register(("msf_prepare_mutation",), "ms_football", "msf.prepare_mutation")
_register(("msf_commit_mutation",), "ms_football", "msf.commit_mutation")
_register(
    ("recall_information", "search_agent_knowledge", "agent_knowledge_stats"),
    "memory", "memory.read", SyscallKind.MEMORY,
)
_register(
    ("remember_information", "save_verified_skill", "save_feedback_lesson"),
    "memory", "memory.write", SyscallKind.MEMORY,
)
_register(
    ("get_current_time", "reset_conversation_context", "return_to_standby"),
    "interaction", "interaction.session",
)


class RuntimeCapabilityResolver:
    """Explicit tool -> agent/capability mapping for the live runtime."""

    def resolve(self, tool_name: str) -> LiveCapabilityRoute | None:
        name = str(tool_name or "").strip()
        raw = _TOOL_ROUTES.get(name)
        if raw is None:
            return None
        agent_id, capability, kind = raw
        return LiveCapabilityRoute(
            tool_name=name,
            agent_id=agent_id,
            capability=capability,
            syscall_kind=kind,
        )


@dataclass
class GovernanceTurn:
    mission_id: str
    user_text: str
    started_at: float


class KernelGovernedToolRegistry:
    """Synchronous Kernel policy gate around the existing native executor.

    This deliberately reuses the current executor instead of creating a second
    automation engine. Its authority is limited to agent/capability/tool/risk
    authorization and approval requirements.
    """

    def __init__(
        self,
        delegate,
        *,
        registry: CapabilityRegistry | None = None,
        policy: KernelPolicy | None = None,
        resolver: RuntimeCapabilityResolver | None = None,
        event_bus: MissionEventBus | None = None,
        fail_closed: bool = True,
    ):
        self.delegate = delegate
        self.registry = registry or DEFAULT_CAPABILITY_REGISTRY
        self.policy = policy or KernelPolicy(self.registry)
        self.resolver = resolver or RuntimeCapabilityResolver()
        self.event_bus = event_bus
        self.fail_closed = bool(fail_closed)
        self._local = threading.local()

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def ollama_tools(self):
        return self.delegate.ollama_tools()

    def openai_tools(self):
        return self.delegate.openai_tools()

    def begin_turn(self, user_text: str) -> str:
        mission_id = "live_" + uuid.uuid4().hex
        self._local.turn = GovernanceTurn(
            mission_id=mission_id,
            user_text=str(user_text or "")[:3000],
            started_at=time.time(),
        )
        return mission_id

    def _turn(self) -> GovernanceTurn:
        turn = getattr(self._local, "turn", None)
        if turn is None:
            self.begin_turn("")
            turn = self._local.turn
        return turn

    def _request(
        self,
        route: LiveCapabilityRoute,
        arguments: dict[str, Any] | None,
    ) -> KernelRequest:
        turn = self._turn()
        return KernelRequest(
            request_id="req_" + uuid.uuid4().hex,
            mission_id=turn.mission_id,
            syscall_kind=route.syscall_kind,
            capability=route.capability,
            agent_id=route.agent_id,
            payload={
                "tool_name": route.tool_name,
                "arguments": dict(arguments or {}),
            },
            user_id="local-user",
            created_at=time.time(),
        )

    def _emit(
        self,
        kind: EventKind,
        request: KernelRequest,
        *,
        success: bool | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(
                BusEvent(
                    kind=kind.value,
                    mission_id=request.mission_id,
                    agent_id=request.agent_id,
                    component="live_kernel_governance",
                    success=success,
                    payload={
                        "request_id": request.request_id,
                        "capability": request.capability,
                        **dict(payload or {}),
                    },
                )
            )
        except Exception:
            pass

    def _decision(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ):
        route = self.resolver.resolve(name)
        if route is None:
            return None, None, None
        request = self._request(route, arguments)
        return route, request, self.policy.authorize(request)

    def requires_confirmation(self, name: str) -> bool:
        if self.delegate.requires_confirmation(name):
            return True
        route = self.resolver.resolve(name)
        if route is None:
            return False
        request = self._request(route, {})
        decision = self.policy.authorize(request)
        return bool(decision.allowed and decision.requires_approval)

    @staticmethod
    def _blocked(
        name: str,
        *,
        reason: str,
        route: LiveCapabilityRoute | None = None,
        risk: RiskLevel | None = None,
    ) -> AgentActionResult:
        return AgentActionResult(
            name=name,
            success=False,
            message=(
                "Le Kernel a bloqué cet outil car il n'est pas autorisé "
                "dans le périmètre actuel."
            ),
            detail=json.dumps(
                {
                    "kernel_governance": True,
                    "allowed": False,
                    "reason": reason,
                    "agent_id": route.agent_id if route else "",
                    "capability": route.capability if route else "",
                    "risk": risk.value if risk else "",
                    "verified": False,
                },
                ensure_ascii=False,
            ),
        )

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        *,
        approved: bool = False,
    ) -> AgentActionResult:
        tool_name = str(name or "").strip()
        route, request, decision = self._decision(tool_name, arguments)
        if route is None or request is None or decision is None:
            if self.fail_closed:
                return self._blocked(tool_name, reason="unmapped_live_tool")
            return self.delegate.execute(
                tool_name, arguments, approved=approved
            )

        self._emit(
            EventKind.AGENT_SELECTED,
            request,
            payload={
                "tool_name": tool_name,
                "agent_id": route.agent_id,
                "reason": "capability_manifest",
            },
        )

        if not decision.allowed:
            self._emit(
                EventKind.SYSCALL_COMPLETED,
                request,
                success=False,
                payload={
                    "tool_name": tool_name,
                    "status": "rejected",
                    "reason": decision.reason,
                },
            )
            return self._blocked(
                tool_name,
                reason=decision.reason,
                route=route,
                risk=decision.risk,
            )

        if decision.requires_approval and not approved:
            self._emit(
                EventKind.APPROVAL_REQUESTED,
                request,
                payload={
                    "tool_name": tool_name,
                    "risk": decision.risk.value,
                    "source": "live_kernel_policy",
                },
            )
            return AgentActionResult(
                name=tool_name,
                success=False,
                message="Cette action nécessite votre confirmation explicite.",
                detail=json.dumps(
                    {
                        "kernel_governance": True,
                        "allowed": True,
                        "approval_required": True,
                        "agent_id": route.agent_id,
                        "capability": route.capability,
                        "risk": decision.risk.value,
                        "verified": False,
                    },
                    ensure_ascii=False,
                ),
            )

        self._emit(
            EventKind.SYSCALL_STARTED,
            request,
            payload={
                "tool_name": tool_name,
                "risk": decision.risk.value,
                "approved": bool(approved),
            },
        )
        result = self.delegate.execute(
            tool_name, arguments, approved=approved
        )
        self._emit(
            EventKind.SYSCALL_COMPLETED,
            request,
            success=result.success,
            payload={
                "tool_name": tool_name,
                "risk": decision.risk.value,
                "approved": bool(approved),
                "status": "succeeded" if result.success else "failed",
            },
        )
        return result


class KernelGovernanceRuntime:
    """Bind a policy mission identity to one authoritative user turn."""

    def __init__(self, delegate, tools: KernelGovernedToolRegistry):
        self.delegate = delegate
        self.tools = tools
        self.event_bus = getattr(delegate, "event_bus", None) or tools.event_bus
        self.model = getattr(delegate, "model", "")
        self.provider_name = getattr(delegate, "provider_name", "")

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def warm_up(self, *, log=None) -> None:
        return self.delegate.warm_up(log=log)

    def reset(self) -> None:
        return self.delegate.reset()

    def run(self, user_text: str, *, log=None, phase=None):
        mission_id = self.tools.begin_turn(user_text)
        if log:
            log(
                "[KERNEL_LIVE] governance=1 "
                f"mission_id={mission_id} authority=policy_only scheduler=0"
            )
        return self.delegate.run(user_text, log=log, phase=phase)
