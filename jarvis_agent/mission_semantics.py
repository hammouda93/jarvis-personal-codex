from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .event_bus import BusEvent, MissionEventBus
from .kernel_contracts import EventKind, MissionContext, MissionStatus
from .mission_context_store import MissionContextStore
from .task_graph import MissionTaskGraph, TaskNode, TaskStatus
from .task_graph_store import TaskGraphStore
from .tracing_runtime import _verification_evidence


# Read-only tools can satisfy a step by returning actual data. Mutation success
# requires structured observed evidence, even if the model asks for tool_success.
READ_ONLY_TOOLS = frozenset({
    "get_current_time", "list_windows", "inspect_active_window", "observe_screen",
    "recall_information", "search_agent_knowledge", "agent_knowledge_stats",
    "msf_capabilities", "msf_describe_schema", "msf_count_records", "msf_query_records",
    "msf_readonly_sql", "msf_search_code", "msf_list_routes", "msf_resolve_route",
})
# These steps may express only that a launch/navigation request returned;
# observation must be a separate step when actual visible state matters.
RESULT_ONLY_TOOLS = READ_ONLY_TOOLS | frozenset({
    "open_application", "open_file", "open_folder", "open_url", "search_web", "activate_window",
})
_EVIDENCE_FIELDS = frozenset({
    "value", "value_length", "after", "observed_state", "evidence", "proof",
    "visible_tabs", "window_closed_as_last_tab",
})
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid_semantic_identifier")
    return value


def _bounded_json(value: Any, *, limit=24000) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(encoded) > limit:
        raise ValueError("semantic_payload_too_large")
    return json.loads(encoded)


class SemanticMissionSession:
    """Persistent proposed plans with mechanically checked step criteria.

    The context snapshot is canonical and includes the DAG in one versioned
    transaction. TaskGraphStore is a recoverable projection. No tool is invoked
    by restoring a plan, and plan satisfaction is not semantic goal coverage.
    """

    def __init__(self, *, base_dir: str | Path, owner_user_id="local-user",
                 event_bus: MissionEventBus | None = None):
        root = Path(base_dir)
        self.context_store = MissionContextStore(root / "semantic_missions.sqlite3")
        self.graph_store = TaskGraphStore(root / "semantic_graphs.sqlite3")
        self.owner_user_id = str(owner_user_id)
        self.event_bus = event_bus
        self.active_id: str | None = None
        self.user_text = ""

    def begin_turn(self, user_text: str) -> None:
        self.user_text = str(user_text or "")[:6000]

    def clear_active(self) -> None:
        if self.active_id:
            context, graph, _ = self._load()
            self.active_id = None
            self._emit(context, graph)
        self.active_id = None

    def _load(self, mission_id: str | None = None):
        key = mission_id or self.active_id
        loaded = self.context_store.load(key) if key else None
        if loaded is None:
            raise ValueError("semantic_mission_not_found")
        context, version = loaded
        if context.user_id != self.owner_user_id:
            raise ValueError("semantic_mission_not_owned")
        graph = MissionTaskGraph.from_dict(context.expected_state["graph"])
        return context, graph, version

    def _save(self, context, graph, version) -> None:
        context.expected_state["graph"] = graph.as_dict()
        self.context_store.save(context, expected_version=version)
        try:
            self.graph_store.save(graph)
        except Exception:
            # The canonical snapshot already persisted the full graph. A
            # projection outage cannot lose or repeat a completed native action.
            pass
        self._emit(context, graph)

    def _emit(self, context, graph) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(BusEvent(
            kind=EventKind.MISSION_UPDATED.value, mission_id=context.mission_id,
            payload={
                "source": "semantic_mission", "status": context.status.value,
                "step_counts": graph.summary(),
                "plan_verification": context.observed_state.get("plan_verification", "pending"),
                "goal_coverage": "not_evaluated", "active": self.active_id == context.mission_id,
            }, component="mission_semantics", agent_id="interaction",
            event_id=f"e_{uuid.uuid4().hex}", created_at=time.time(),
        ))

    @staticmethod
    def _validate_criterion(raw, tool_name, entities):
        criterion = _bounded_json(raw or {})
        if not isinstance(criterion, dict) or criterion.get("kind") not in {"tool_success", "verified_result"}:
            raise ValueError("invalid_completion_criterion")
        if criterion["kind"] == "tool_success" and tool_name not in RESULT_ONLY_TOOLS:
            raise ValueError("mutation_requires_observed_evidence")
        if criterion.get("field") and criterion["field"] not in _EVIDENCE_FIELDS:
            raise ValueError("criterion_field_not_observed_evidence")
        if "equals" in criterion or "equals_entity" in criterion:
            if not criterion.get("field"):
                raise ValueError("criterion_comparison_requires_field")
        if "equals" in criterion and "equals_entity" in criterion:
            raise ValueError("ambiguous_criterion_comparison")
        if "equals_entity" in criterion and criterion["equals_entity"] not in entities:
            raise ValueError("unknown_criterion_entity")
        return criterion

    def create_plan(self, *, entities=None, constraints=None, steps=None, known_tools=()) -> dict:
        if not self.user_text:
            raise ValueError("mission_requires_real_user_request")
        if self.active_id:
            current, _, _ = self._load()
            if current.status in {MissionStatus.WAITING_EXTERNAL, MissionStatus.BLOCKED, MissionStatus.WAITING_USER}:
                raise ValueError("active_mission_requires_observation_or_resume")
        entities = _bounded_json(entities or {}, limit=4000)
        if not isinstance(entities, dict) or len(entities) > 20:
            raise ValueError("invalid_mission_entities")
        for name, value in entities.items():
            _identifier(name)
            if not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise ValueError("invalid_entity_value")
        constraints = _bounded_json(constraints or [], limit=4000)
        if not isinstance(constraints, list) or len(constraints) > 15 or any(
            not isinstance(item, str) or len(item) > 500 for item in constraints
        ):
            raise ValueError("invalid_mission_constraints")
        steps = _bounded_json(steps or [])
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ValueError("mission_requires_one_to_twenty_steps")
        mission_id = f"m_{uuid.uuid4().hex}"
        graph = MissionTaskGraph(mission_id)
        known = set(known_tools)
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError("invalid_mission_step")
            task_id = _identifier(step.get("id"))
            tool_name = str(step.get("tool_name") or "")
            if tool_name not in known:
                raise ValueError("unknown_planned_tool")
            dependencies = step.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise ValueError("invalid_step_dependencies")
            bindings = step.get("entity_bindings", {})
            if not isinstance(bindings, dict):
                raise ValueError("invalid_entity_bindings")
            for argument, entity in bindings.items():
                _identifier(argument)
                if argument in {"ref", "x", "y", "mission_step_id"} or entity not in entities:
                    raise ValueError("invalid_or_transient_entity_binding")
            description = step.get("description", "")
            if not isinstance(description, str) or len(description) > 500:
                raise ValueError("invalid_step_description")
            criterion = self._validate_criterion(step.get("criterion"), tool_name, entities)
            graph.add(TaskNode(
                task_id=task_id, mission_id=mission_id, capability="native." + tool_name,
                agent_id="interaction", dependencies={_identifier(dep) for dep in dependencies},
                priority=index, payload={"description": description, "tool_name": tool_name,
                    "entity_bindings": dict(bindings), "criterion": criterion},
            ))
        ids = {node.task_id for node in graph.nodes()}
        if any(node.dependencies - ids for node in graph.nodes()):
            raise ValueError("unknown_step_dependency")
        context = MissionContext(
            mission_id=mission_id, user_goal=self.user_text, user_id=self.owner_user_id,
            owner_agent_id="interaction", status=MissionStatus.RUNNING,
            expected_state={"semantics_version": 1, "entities": entities,
                "constraints": constraints, "entity_revisions": [], "goal_coverage": "not_evaluated"},
            observed_state={"plan_verification": "pending", "attempts": {}},
        )
        self.active_id = mission_id
        graph.ready()
        self._save(context, graph, 0)
        return self.state()

    def state(self, mission_id: str | None = None) -> dict:
        context, graph, _ = self._load(mission_id)
        return {
            "mission_id": context.mission_id, "user_goal": context.user_goal,
            "status": context.status.value, "entities": context.expected_state["entities"],
            "constraints": context.expected_state["constraints"],
            "entity_revisions": context.expected_state["entity_revisions"],
            "steps": [{"id": node.task_id, "tool_name": node.payload["tool_name"],
                "description": node.payload["description"], "status": node.status.value,
                "dependencies": sorted(node.dependencies), "criterion": node.payload["criterion"],
                "entity_bindings": node.payload["entity_bindings"], "error": node.error,
                "attempts": context.observed_state["attempts"].get(node.task_id, 0)}
                for node in graph.nodes()],
            "plan_verification": context.observed_state["plan_verification"],
            "goal_coverage": "not_evaluated", "mission_verified": False,
            "next_step_ids": [node.task_id for node in graph.nodes() if node.status == TaskStatus.READY],
        }

    def pause(self) -> dict:
        context, graph, version = self._load()
        context.status = MissionStatus.WAITING_USER
        self._save(context, graph, version)
        return self.state()

    def resume(self, mission_id: str) -> dict:
        context, graph, version = self._load(_identifier(mission_id))
        self.active_id = context.mission_id
        for node in graph.nodes():
            if node.status == TaskStatus.RUNNING:
                node.status = TaskStatus.WAITING_EXTERNAL
                node.error = "interrupted_action_requires_observation"
        context.status = MissionStatus.RUNNING
        if any(node.status == TaskStatus.WAITING_EXTERNAL for node in graph.nodes()):
            context.status = MissionStatus.WAITING_EXTERNAL
        graph.ready()
        self._save(context, graph, version)
        return self.state()

    def resumable(self) -> list[dict]:
        return self.context_store.list_resumable(user_id=self.owner_user_id, limit=20)

    def correct_entity(self, *, name: str, value: str) -> dict:
        context, graph, version = self._load()
        entities = context.expected_state["entities"]
        if name not in entities or not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise ValueError("invalid_entity_correction")
        # The model can identify which entity was corrected; the new value must
        # actually come from the human turn, not from an invented tool argument.
        if value.casefold() not in self.user_text.casefold():
            raise ValueError("correction_value_not_in_user_turn")
        if entities[name] == value:
            return self.state()
        revisions = context.expected_state["entity_revisions"]
        if len(revisions) >= 100:
            raise ValueError("entity_revision_limit_reached")
        revisions.append({"entity": name, "old": entities[name], "new": value})
        entities[name] = value
        affected = {node.task_id for node in graph.nodes() if
            name in node.payload["entity_bindings"].values()
            or node.payload["criterion"].get("equals_entity") == name}
        while True:
            enlarged = affected | {node.task_id for node in graph.nodes() if node.dependencies & affected}
            if enlarged == affected:
                break
            affected = enlarged
        for node in graph.nodes():
            if node.task_id in affected:
                was_executed = context.observed_state["attempts"].get(node.task_id, 0) > 0
                node.status = TaskStatus.PENDING
                node.result = {}
                node.error = "entity_changed"
                # An already attempted mutation may have affected the old target.
                # A correction is not permission to repeat it on a new target.
                if was_executed and node.payload["tool_name"] not in RESULT_ONLY_TOOLS:
                    node.status = TaskStatus.WAITING_EXTERNAL
                    node.error = "entity_changed_after_mutation_requires_observation"
        context.proof_refs = []
        context.observed_state["plan_verification"] = "pending"
        context.status = MissionStatus.RUNNING
        if any(node.status == TaskStatus.WAITING_EXTERNAL for node in graph.nodes()):
            context.status = MissionStatus.WAITING_EXTERNAL
        graph.ready()
        self._save(context, graph, version)
        return self.state()

    def before_action(self, *, tool_name: str, arguments: dict, step_id: str) -> tuple[str, str, dict]:
        context, graph, version = self._load()
        if context.status != MissionStatus.RUNNING:
            raise ValueError("mission_is_paused_or_requires_observation")
        node = graph.get(step_id)
        if node is None or node.payload["tool_name"] != tool_name:
            raise ValueError("tool_does_not_match_mission_step")
        if node.status not in {TaskStatus.PENDING, TaskStatus.READY}:
            raise ValueError("step_already_executed_or_requires_observation")
        graph.mark_running(step_id)
        bound = dict(arguments)
        for key, entity in node.payload["entity_bindings"].items():
            bound[key] = context.expected_state["entities"][entity]
        attempts = context.observed_state["attempts"]
        attempts[step_id] = attempts.get(step_id, 0) + 1
        context.current_step_id = step_id
        context.current_step = node.payload["description"]
        self._save(context, graph, version)  # durable intent precedes the native action
        return context.mission_id, step_id, bound

    def after_action(self, mission_id: str, step_id: str, result) -> None:
        context, graph, version = self._load(mission_id)
        node = graph.get(step_id)
        if node is None or node.status != TaskStatus.RUNNING:
            raise ValueError("step_result_without_running_step")
        criterion = node.payload["criterion"]
        evidence = _verification_evidence(result)
        satisfied = result.name == node.payload["tool_name"] and bool(result.success) and (
            criterion["kind"] == "tool_success" or bool(evidence)
        )
        if criterion.get("field"):
            field = criterion["field"]
            satisfied = satisfied and field in evidence
            if "equals_entity" in criterion:
                expected = context.expected_state["entities"][criterion["equals_entity"]]
                actual = evidence.get(field)
                satisfied = satisfied and type(actual) is type(expected) and actual == expected
            elif "equals" in criterion:
                actual, expected = evidence.get(field), criterion["equals"]
                satisfied = satisfied and type(actual) is type(expected) and actual == expected
        node.result = {"success": bool(result.success), "criterion_satisfied": bool(satisfied)}
        if satisfied:
            graph.mark_completed(step_id, node.result)
            if evidence:
                context.proof_refs.append(f"{mission_id}/{step_id}/{context.observed_state['attempts'][step_id]}")
        elif not result.success:
            graph.mark_failed(step_id, "native_tool_failed")
            context.status = MissionStatus.BLOCKED
        else:
            node.status = TaskStatus.WAITING_EXTERNAL
            node.error = "success_without_matching_observed_proof"
            context.status = MissionStatus.WAITING_EXTERNAL
        graph.ready()
        all_satisfied = all(node.status == TaskStatus.COMPLETED for node in graph.nodes())
        context.observed_state["plan_verification"] = "criteria_satisfied" if all_satisfied else "pending"
        # No semantic goal-completed verdict: coverage of this model-proposed
        # plan against the full user request has not been independently checked.
        context.current_step_id = None
        context.current_step = ""
        self._save(context, graph, version)

    def mark_interrupted(self, mission_id: str, step_id: str) -> None:
        context, graph, version = self._load(mission_id)
        node = graph.get(step_id)
        if node is not None:
            node.status = TaskStatus.WAITING_EXTERNAL
            node.error = "native_exception_requires_observation"
        context.status = MissionStatus.WAITING_EXTERNAL
        self._save(context, graph, version)
