import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from jarvis_agent.agent_runtime import build_agent_runtime
from jarvis_agent.config import settings
from jarvis_agent.event_bus import MissionEventBus
from jarvis_agent.kernel_contracts import MissionStatus
from jarvis_agent.mission_context_store import MissionContextStore
from jarvis_agent.mission_semantics import SemanticMissionSession
from jarvis_agent.native_tools import AgentActionResult
from jarvis_agent.runtime_activity_panel import RuntimeActivityPanel
from jarvis_agent.semantic_mission_runtime import SemanticMissionRuntime, SemanticMissionTools
from jarvis_agent.task_graph import MissionTaskGraph, TaskNode
from jarvis_agent.tracing_runtime import StructuredTracingRuntime, TracingToolRegistry
from tests.test_agent_runtime import FakeGroqAgent, FakeOllamaAgent, FakeOpenAIAgent


def plan():
    return {"entities": {"app": "Bloc-notes", "text": "Bonjour"},
        "constraints": ["Ne pas envoyer ni enregistrer le document."], "steps": [
            {"id": "open", "description": "Lancer l'application", "tool_name": "open_application",
                "entity_bindings": {"name": "app"}, "criterion": {"kind": "tool_success"}},
            {"id": "write", "description": "Écrire et constater la valeur", "tool_name": "write_ui_element",
                "dependencies": ["open"], "entity_bindings": {"text": "text"},
                "criterion": {"kind": "verified_result", "field": "value", "equals_entity": "text"}},
        ]}


class DummyNativeTools:
    knowledge = None
    memory = None

    def __init__(self):
        self.calls = []
        self.results = []

    def ollama_tools(self):
        return [{"type": "function", "function": {
            "name": name, "description": name,
            "parameters": {"type": "object", "properties": {"name": {"type": "string"},
                "text": {"type": "string"}}, "required": [], "additionalProperties": False},
        }} for name in ("open_application", "write_ui_element", "inspect_active_window", "list_windows", "reset_conversation_context")]

    def requires_confirmation(self, name):
        return False

    def execute(self, name, arguments, *, approved=False):
        self.calls.append((name, dict(arguments), approved))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        detail = json.dumps({"verified": True, "value": arguments.get("text", "")}) if name == "write_ui_element" else "opened"
        return AgentActionResult(name, True, "ok", detail)


def model_call(name, args, provider, call_id):
    if provider == "ollama":
        return {"message": {"tool_calls": [{"function": {"name": name, "arguments": args}}]}}
    return {"id": call_id, "output": [{"type": "function_call", "call_id": call_id,
        "name": name, "arguments": json.dumps(args, ensure_ascii=False)}]}


def model_reply(text, provider):
    if provider == "ollama":
        return {"message": {"content": text}}
    return {"id": "response_final", "output": [{"type": "message",
        "content": [{"type": "output_text", "text": text}]}]}


class SemanticMissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = []
        self.bus = MissionEventBus()
        self.bus.subscribe(None, self.events.append)
        self.session = SemanticMissionSession(base_dir=self.root, event_bus=self.bus)
        self.native = DummyNativeTools()
        self.tools = SemanticMissionTools(self.native, self.session)
        self.session.begin_turn("Ouvre Bloc-notes et écris Bonjour, sans enregistrer ni envoyer.")

    def create(self, value=None):
        return self.session.create_plan(known_tools={
            item["function"]["name"] for item in self.native.ollama_tools()
        }, **(value or plan()))

    def execute_open(self):
        return self.tools.execute("open_application", {"name": "OLD", "mission_step_id": "open"})

    def test_original_human_goal_and_pending_dependencies_are_persisted(self):
        state = self.create()
        self.assertEqual(state["user_goal"], self.session.user_text)
        self.assertEqual(state["next_step_ids"], ["open"])
        self.assertFalse(state["mission_verified"])
        self.assertEqual(state["goal_coverage"], "not_evaluated")

    def test_partial_success_does_not_complete_plan_or_mission(self):
        self.create()
        self.execute_open()
        state = self.session.state()
        self.assertEqual(state["steps"][0]["status"], "completed")
        self.assertEqual(state["next_step_ids"], ["write"])
        self.assertEqual(state["plan_verification"], "pending")
        self.assertFalse(state["mission_verified"])

    def test_matched_proof_satisfies_plan_without_claiming_goal_coverage(self):
        self.create()
        self.execute_open()
        self.tools.execute("write_ui_element", {"text": "OLD", "mission_step_id": "write"})
        state = self.session.state()
        self.assertEqual(self.native.calls[-1][1], {"text": "Bonjour"})
        self.assertEqual(state["plan_verification"], "criteria_satisfied")
        self.assertFalse(state["mission_verified"])
        self.assertNotEqual(state["status"], "completed")

    def test_mutation_cannot_use_success_only_criterion(self):
        value = plan()
        value["steps"][1]["criterion"] = {"kind": "tool_success"}
        with self.assertRaisesRegex(ValueError, "mutation_requires_observed_evidence"):
            self.create(value)
        self.assertEqual(self.session.resumable(), [])

    def test_success_without_proof_blocks_dependent_work(self):
        self.create()
        self.execute_open()
        self.native.results = [AgentActionResult("write_ui_element", True, "ok", "done")]
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        state = self.session.state()
        self.assertEqual(state["status"], "waiting_external")
        self.assertEqual(state["plan_verification"], "pending")
        self.assertEqual(state["steps"][1]["status"], "waiting_external")

    def test_proof_for_wrong_value_does_not_satisfy_requested_text(self):
        self.create()
        self.execute_open()
        self.native.results = [AgentActionResult("write_ui_element", True, "ok",
            json.dumps({"verified": True, "value": "Mauvaise valeur"}))]
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        self.assertEqual(self.session.state()["plan_verification"], "pending")

    def test_target_name_only_is_not_observed_evidence(self):
        self.create()
        self.execute_open()
        self.native.results = [AgentActionResult("write_ui_element", True, "ok",
            json.dumps({"verified": True, "target": "Bonjour"}))]
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        self.assertEqual(self.session.state()["status"], "waiting_external")

    def test_other_tool_result_cannot_satisfy_the_step(self):
        self.create()
        self.execute_open()
        self.native.results = [AgentActionResult("remember_information", True, "ok",
            json.dumps({"verified": True, "value": "Bonjour"}))]
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        self.assertEqual(self.session.state()["plan_verification"], "pending")

    def test_empty_observed_value_can_verify_a_requested_clear(self):
        value = plan()
        value["steps"][1]["entity_bindings"] = {}
        value["steps"][1]["criterion"] = {"kind": "verified_result", "field": "value", "equals": ""}
        self.create(value)
        self.execute_open()
        self.tools.execute("write_ui_element", {"text": "", "mission_step_id": "write"})
        self.assertEqual(self.session.state()["plan_verification"], "criteria_satisfied")

    def test_boolean_cannot_masquerade_as_an_integer_count(self):
        value = plan()
        value["steps"][1]["criterion"] = {"kind": "verified_result", "field": "value_length", "equals": 1}
        self.create(value)
        self.execute_open()
        self.native.results = [AgentActionResult("write_ui_element", True, "ok",
            json.dumps({"verified": True, "value_length": True}))]
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        self.assertEqual(self.session.state()["plan_verification"], "pending")

    def test_out_of_order_action_never_reaches_native_tool(self):
        self.create()
        result = self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        self.assertFalse(result.success)
        self.assertEqual(self.native.calls, [])

    def test_unassigned_mutation_and_wrong_tool_are_blocked(self):
        self.create()
        self.assertFalse(self.tools.execute("open_application", {"name": "Bloc-notes"}).success)
        self.assertFalse(self.tools.execute("write_ui_element", {"mission_step_id": "open"}).success)
        self.assertEqual(self.native.calls, [])

    def test_completed_step_cannot_be_repeated(self):
        self.create()
        self.execute_open()
        self.assertFalse(self.execute_open().success)
        self.assertEqual(len(self.native.calls), 1)

    def test_entity_correction_changes_bound_arguments_without_typing_the_name(self):
        self.create()
        self.session.begin_turn("Non, l'application est Éditeur Test.")
        result = self.tools.execute("correct_mission_entity", {"name": "app", "value": "Éditeur Test"})
        self.assertTrue(result.success)
        self.assertEqual(self.native.calls, [])
        self.execute_open()
        self.assertEqual(self.native.calls[0][1]["name"], "Éditeur Test")

    def test_invented_entity_correction_is_rejected(self):
        self.create()
        self.session.begin_turn("Non, Chaima.")
        result = self.tools.execute("correct_mission_entity", {"name": "app", "value": "Chrome"})
        self.assertFalse(result.success)
        self.assertEqual(self.session.state()["entities"]["app"], "Bloc-notes")

    def test_entity_correction_after_mutation_invalidates_proof_and_requires_observation(self):
        self.create()
        self.execute_open()
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        self.session.begin_turn("Non, écris Salut.")
        self.session.correct_entity(name="text", value="Salut")
        state = self.session.state()
        self.assertEqual(state["status"], "waiting_external")
        self.assertEqual(state["plan_verification"], "pending")
        self.assertFalse(self.tools.execute("write_ui_element", {"mission_step_id": "write"}).success)
        self.assertEqual(len(self.native.calls), 2)

    def test_pause_persists_and_blocks_mutations(self):
        state = self.create()
        self.session.pause()
        self.assertFalse(self.execute_open().success)
        fresh = SemanticMissionSession(base_dir=self.root)
        self.assertEqual(fresh.state(state["mission_id"])["status"], "waiting_user")

    def test_restore_after_restart_does_not_execute_any_tool(self):
        state = self.create()
        self.execute_open()
        fresh = SemanticMissionSession(base_dir=self.root)
        restored = fresh.resume(state["mission_id"])
        self.assertEqual(restored["next_step_ids"], ["write"])
        self.assertEqual(len(self.native.calls), 1)

    def test_interrupted_mutation_is_not_replayed_after_restart(self):
        state = self.create()
        self.execute_open()
        self.session.before_action(tool_name="write_ui_element", arguments={}, step_id="write")
        fresh = SemanticMissionSession(base_dir=self.root)
        restored = fresh.resume(state["mission_id"])
        self.assertEqual(restored["status"], "waiting_external")
        tools = SemanticMissionTools(self.native, fresh)
        self.assertFalse(tools.execute("write_ui_element", {"mission_step_id": "write"}).success)
        self.assertEqual(len(self.native.calls), 1)

    def test_projection_failure_keeps_canonical_resume_snapshot(self):
        with patch.object(self.session.graph_store, "save", side_effect=OSError("fixture")):
            state = self.create()
            self.execute_open()
        fresh = SemanticMissionSession(base_dir=self.root)
        self.assertEqual(fresh.resume(state["mission_id"])["next_step_ids"], ["write"])

    def test_native_exception_is_preserved_and_marks_uncertain_outcome(self):
        self.create()
        failure = OSError("fixture")
        self.native.results = [failure]
        with self.assertRaises(OSError) as raised:
            self.execute_open()
        self.assertIs(raised.exception, failure)
        self.assertEqual(self.session.state()["status"], "waiting_external")

    def test_another_user_cannot_load_or_resume_plan(self):
        state = self.create()
        foreign = SemanticMissionSession(base_dir=self.root, owner_user_id="other-user")
        with self.assertRaisesRegex(ValueError, "not_owned"):
            foreign.resume(state["mission_id"])
        self.assertEqual(foreign.resumable(), [])

    def test_cycle_and_missing_dependency_leave_no_partial_plan(self):
        value = plan()
        value["steps"][0]["dependencies"] = ["write"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.create(value)
        value = plan()
        value["steps"][1]["dependencies"] = ["absent"]
        with self.assertRaisesRegex(ValueError, "unknown_step_dependency"):
            self.create(value)
        self.assertEqual(self.session.resumable(), [])

    def test_recreating_plan_cannot_bypass_uncertain_mutation(self):
        self.create()
        self.execute_open()
        self.native.results = [AgentActionResult("write_ui_element", True, "ok", "done")]
        self.tools.execute("write_ui_element", {"mission_step_id": "write"})
        with self.assertRaisesRegex(ValueError, "requires_observation"):
            self.create()

    def test_actual_provider_loops_can_plan_execute_and_report_distinct_verification(self):
        for provider, agent_type in (
            ("groq", FakeGroqAgent), ("ollama", FakeOllamaAgent), ("openai", FakeOpenAIAgent),
        ):
            with self.subTest(provider=provider):
                session = SemanticMissionSession(base_dir=self.root / provider, event_bus=self.bus)
                tools = SemanticMissionTools(self.native, session)
                tracing = TracingToolRegistry(tools, event_bus=self.bus)
                agent = agent_type(tracing, [
                    model_call("create_mission_plan", plan(), provider, "create_plan"),
                    model_call("open_application", {"mission_step_id": "open"}, provider, "launch"),
                    model_call("inspect_active_window", {}, provider, "inspect"),
                    model_call("write_ui_element", {"mission_step_id": "write"}, provider, "write"),
                    model_reply("La mission est terminée.", provider),
                ])
                runtime = StructuredTracingRuntime(SemanticMissionRuntime(agent, session), tracing)
                result = runtime.run("Ouvre Bloc-notes et écris Bonjour.")
                self.assertEqual(result.plan_verification, "criteria_satisfied")
                self.assertIn("objectif global reste à vérifier", result.text)
                self.assertTrue(any(event.kind == "proof" for event in self.events))
                self.assertTrue(any(event.kind == "mission.updated" for event in self.events))

    def test_builder_uses_opt_in_mission_proxy_without_api_call(self):
        configured = replace(settings, semantic_missions_enabled=True, semantic_missions_dir=str(self.root),
            agent_provider="cerebras", runtime_observability_enabled=True, structured_tracing_enabled=False)
        with patch("jarvis_agent.agent_runtime.settings", configured):
            runtime = build_agent_runtime()
        self.assertIsInstance(runtime, StructuredTracingRuntime)
        self.assertIsInstance(runtime.delegate, SemanticMissionRuntime)
        self.assertIn("create_mission_plan", {item["function"]["name"] for item in runtime.tools.ollama_tools()})

    def test_qt_projection_labels_plan_and_goal_separately(self):
        app = QApplication.instance() or QApplication([])
        panel = RuntimeActivityPanel()
        self.bus.subscribe(None, panel.on_event)
        self.create()
        self.execute_open()
        app.processEvents()
        self.assertIn("1/2 étapes", panel.mission_summary.text())
        self.assertIn("objectif global non évalué", panel.mission_summary.text())
        self.session.clear_active()
        app.processEvents()
        self.assertIn("aucun plan actif", panel.mission_summary.text())
        self.assertEqual(len(self.session.resumable()), 1)
        panel.close()

    def test_mark_status_updates_loaded_state_and_version(self):
        state = self.create()
        context, version = self.session.context_store.load(state["mission_id"])
        self.session.context_store.mark_status(state["mission_id"], MissionStatus.BLOCKED)
        reloaded, new_version = self.session.context_store.load(state["mission_id"])
        self.assertEqual(reloaded.status, MissionStatus.BLOCKED)
        self.assertEqual(new_version, version + 1)
        with self.assertRaisesRegex(RuntimeError, "version_conflict"):
            self.session.context_store.save(context, expected_version=version)

    def test_two_store_instances_cannot_overwrite_same_version(self):
        state = self.create()
        path = self.session.context_store.path
        barrier = threading.Barrier(2)
        outcomes = []
        def update(label):
            store = MissionContextStore(path)
            context, version = store.load(state["mission_id"])
            context.current_step = label
            barrier.wait(timeout=10)
            try:
                store.save(context, expected_version=version)
                outcomes.append("saved")
            except RuntimeError:
                outcomes.append("conflict")
        threads = [threading.Thread(target=update, args=(str(i),)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(outcomes), ["conflict", "saved"])

    def test_canonical_database_file_is_released_after_an_operation(self):
        state = self.create()
        self.session.state()
        original = self.session.context_store.path
        renamed = original.with_name("released_missions.sqlite3")
        original.rename(renamed)
        restored, _ = MissionContextStore(renamed).load(state["mission_id"])
        self.assertEqual(restored.user_goal, self.session.user_text)

    def test_graph_projection_preserves_zero_priority_order(self):
        state = self.create()
        restored = self.session.graph_store.load(state["mission_id"])
        self.assertEqual([node.task_id for node in restored.nodes()], ["open", "write"])
        self.assertEqual(restored.nodes()[0].priority, 0)

    def test_invalid_graph_add_rolls_back_the_candidate_node(self):
        graph = MissionTaskGraph("test")
        graph.add(TaskNode("a", "test", "read", "interaction", dependencies={"b"}))
        with self.assertRaisesRegex(ValueError, "cycle"):
            graph.add(TaskNode("b", "test", "read", "interaction", dependencies={"a"}))
        self.assertIsNone(graph.get("b"))
        graph.add(TaskNode("b", "test", "read", "interaction"))
        self.assertEqual([node.task_id for node in graph.ready()], ["b"])


if __name__ == "__main__":
    unittest.main()
