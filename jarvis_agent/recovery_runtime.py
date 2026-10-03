from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Any

from .native_tools import AgentActionResult


_OBSERVATION_TOOLS = frozenset(
    {
        "list_windows",
        "inspect_active_window",
        "ground_ui_role",
        "observe_screen",
        "get_current_time",
        "recall_information",
        "search_agent_knowledge",
        "agent_knowledge_stats",
        "research_web",
        "msf_capabilities",
        "msf_describe_schema",
        "msf_count_records",
        "msf_query_records",
        "msf_readonly_sql",
        "msf_search_code",
        "msf_list_routes",
        "msf_resolve_route",
    }
)

_UI_MUTATION_TOOLS = frozenset(
    {
        "click_ui_element",
        "write_ui_element",
        "click_visual_target",
        "write_visual_target",
        "type_text_active_window",
        "press_key",
        "close_window",
        "close_tab",
    }
)

_MUTATION_TOOLS = _UI_MUTATION_TOOLS | frozenset(
    {
        "open_application",
        "open_file",
        "open_folder",
        "open_url",
        "msf_commit_mutation",
        "remember_information",
        "save_verified_skill",
        "save_feedback_lesson",
    }
)


def _stable_arguments(arguments: dict[str, Any] | None) -> str:
    try:
        return json.dumps(
            arguments or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return repr(arguments or {})


def _signature(name: str, arguments: dict[str, Any] | None) -> str:
    return f"{str(name)}:{_stable_arguments(arguments)}"


def _detail_dict(result: AgentActionResult) -> dict[str, Any]:
    raw = str(result.detail or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_verified(result: AgentActionResult) -> bool:
    detail = _detail_dict(result)
    if detail.get("verified") is True:
        return True
    proof = detail.get("proof")
    return isinstance(proof, dict) and bool(proof)


@dataclass
class TurnRecoveryState:
    user_text: str = ""
    total_calls: int = 0
    consecutive_failures: int = 0
    failed_signatures: set[str] = field(default_factory=set)
    tool_counts: dict[str, int] = field(default_factory=dict)
    mutation_requires_observation: bool = False
    last_failure_tool: str = ""
    blocked_reason: str = ""


@dataclass(frozen=True)
class RecoverySummary:
    total_calls: int
    consecutive_failures: int
    failed_signature_count: int
    tool_counts: dict[str, int]
    safe_stop_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "consecutive_failures": self.consecutive_failures,
            "failed_signature_count": self.failed_signature_count,
            "tool_counts": dict(self.tool_counts),
            "safe_stop_reason": self.safe_stop_reason,
        }


class RecoveryToolRegistry:
    """Turn-scoped safety/recovery boundary around the existing tool registry.

    It prevents blind repetition and requires fresh perception after uncertain
    UI mutation failures. It never invents an application-specific recovery.
    """

    runtime_instructions = """
Recovery boundary:
- Never repeat an identical failed tool call. Diagnose the failure and choose a
  materially different strategy.
- After a failed/uncertain UI mutation, perform fresh observation
  (inspect_active_window, ground_ui_role, or observe_screen when allowed) before
  another UI mutation.
- If the recovery guard reports a budget/loop stop, do not bypass it. Explain
  the unresolved state or ask for the minimum user input required.
- Research is not a substitute for a local capability that should work. Use it
  only when external information is genuinely required or local strategies are
  exhausted.
""".strip()

    def __init__(
        self,
        delegate,
        *,
        max_total_calls: int = 18,
        max_consecutive_failures: int = 4,
        max_same_tool_calls: int = 7,
    ):
        self.delegate = delegate
        self.max_total_calls = max(4, int(max_total_calls))
        self.max_consecutive_failures = max(
            2, int(max_consecutive_failures)
        )
        self.max_same_tool_calls = max(2, int(max_same_tool_calls))
        self._local = threading.local()

    def _state(self) -> TurnRecoveryState:
        state = getattr(self._local, "state", None)
        if state is None:
            state = TurnRecoveryState()
            self._local.state = state
        return state

    def begin_turn(self, user_text: str) -> None:
        self._local.state = TurnRecoveryState(
            user_text=str(user_text or "")[:2000]
        )

    def end_turn(self) -> RecoverySummary:
        state = self._state()
        return RecoverySummary(
            total_calls=state.total_calls,
            consecutive_failures=state.consecutive_failures,
            failed_signature_count=len(state.failed_signatures),
            tool_counts=dict(state.tool_counts),
            safe_stop_reason=state.blocked_reason,
        )

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def ollama_tools(self):
        return self.delegate.ollama_tools()

    def openai_tools(self):
        return self.delegate.openai_tools()

    def requires_confirmation(self, name: str) -> bool:
        return self.delegate.requires_confirmation(name)

    @staticmethod
    def _blocked(
        name: str,
        *,
        reason: str,
        message: str,
        next_actions: list[str],
        signature: str = "",
    ) -> AgentActionResult:
        return AgentActionResult(
            name=name,
            success=False,
            message=message,
            detail=json.dumps(
                {
                    "reason": reason,
                    "recovery_guard": True,
                    "failed_signature": signature,
                    "next_actions": next_actions,
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
        state = self._state()
        tool_name = str(name or "").strip()
        signature = _signature(tool_name, arguments)

        if state.total_calls >= self.max_total_calls:
            state.blocked_reason = "turn_tool_budget_exhausted"
            return self._blocked(
                tool_name,
                reason=state.blocked_reason,
                message=(
                    "Limite de récupération atteinte pour ce tour. "
                    "Arrêt sûr au lieu de poursuivre une boucle."
                ),
                next_actions=["stop_and_report", "ask_minimal_clarification"],
            )

        if signature in state.failed_signatures:
            return self._blocked(
                tool_name,
                reason="identical_failed_call_blocked",
                message=(
                    "Cet appel a déjà échoué avec exactement les mêmes "
                    "arguments. Une stratégie différente est requise."
                ),
                next_actions=[
                    "diagnose_failure",
                    "fresh_observation",
                    "different_strategy",
                ],
                signature=signature,
            )

        count = state.tool_counts.get(tool_name, 0)
        if (
            count >= self.max_same_tool_calls
            and tool_name not in _OBSERVATION_TOOLS
        ):
            state.blocked_reason = "repeated_tool_loop_detected"
            return self._blocked(
                tool_name,
                reason=state.blocked_reason,
                message=(
                    "Trop d'appels du même outil dans ce tour. "
                    "Une autre stratégie ou un arrêt est requis."
                ),
                next_actions=[
                    "different_capability",
                    "stop_and_report",
                ],
            )

        if (
            state.mutation_requires_observation
            and tool_name in _UI_MUTATION_TOOLS
        ):
            return self._blocked(
                tool_name,
                reason="fresh_observation_required",
                message=(
                    "Une mutation UI précédente a échoué ou reste incertaine. "
                    "Réinspectez l'état réel avant une nouvelle mutation."
                ),
                next_actions=[
                    "inspect_active_window",
                    "ground_ui_role",
                    "observe_screen_if_enabled",
                ],
            )

        state.total_calls += 1
        state.tool_counts[tool_name] = count + 1
        result = self.delegate.execute(
            tool_name,
            arguments,
            approved=approved,
        )

        if tool_name in _OBSERVATION_TOOLS and result.success:
            state.mutation_requires_observation = False

        if result.success:
            state.consecutive_failures = 0
            if (
                tool_name in _UI_MUTATION_TOOLS
                and not _is_verified(result)
            ):
                state.mutation_requires_observation = True
            return result

        state.consecutive_failures += 1
        state.last_failure_tool = tool_name
        state.failed_signatures.add(signature)
        if tool_name in _UI_MUTATION_TOOLS:
            state.mutation_requires_observation = True

        if state.consecutive_failures >= self.max_consecutive_failures:
            state.blocked_reason = "consecutive_failure_budget_exhausted"

        return result


class RecoveryGuardRuntime:
    """Outer runtime boundary that scopes recovery state to one user turn."""

    def __init__(self, delegate, tools: RecoveryToolRegistry):
        self.delegate = delegate
        self.tools = tools
        self.event_bus = getattr(delegate, "event_bus", None)
        self.model = getattr(delegate, "model", "")
        self.provider_name = getattr(delegate, "provider_name", "")

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def warm_up(self, *, log=None) -> None:
        return self.delegate.warm_up(log=log)

    def reset(self) -> None:
        self.tools.begin_turn("")
        return self.delegate.reset()

    def run(self, user_text: str, *, log=None, phase=None):
        self.tools.begin_turn(user_text)
        try:
            return self.delegate.run(
                user_text,
                log=log,
                phase=phase,
            )
        finally:
            summary = self.tools.end_turn()
            if log:
                log(
                    "[RECOVERY] "
                    f"calls={summary.total_calls} "
                    f"failures={summary.consecutive_failures} "
                    f"failed_signatures={summary.failed_signature_count} "
                    f"safe_stop={summary.safe_stop_reason or 'none'}"
                )
