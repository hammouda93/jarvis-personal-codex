import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from jarvis_agent.config import settings
from jarvis_agent.event_bus import BusEvent, MissionEventBus
from jarvis_agent.event_journal import StructuredEventJournal, _safe_value
from jarvis_agent.kernel_contracts import EventKind
from jarvis_agent.native_tools import AgentActionResult
from jarvis_agent.runtime_activity import RuntimeActivityState
from jarvis_agent.runtime_activity_panel import RuntimeActivityPanel
from jarvis_agent.tracing_runtime import StructuredTracingRuntime, TracingToolRegistry


class FakeTools:
    knowledge = None

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, name, arguments, *, approved=False):
        self.calls.append((name, arguments, approved))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeRuntime:
    def __init__(self, tools, names):
        self.tools = tools
        self.names = names
        self.result = None

    def run(self, user_text, *, log=None, phase=None):
        if phase:
            phase("thinking")
        actions = []
        for name in self.names:
            if phase:
                phase("acting")
            actions.append(self.tools.execute(name, {"text": user_text}, approved=True))
        self.result = SimpleNamespace(text="done", actions=tuple(actions))
        return self.result

    def reset(self):
        pass

    def warm_up(self, *, log=None):
        pass


def action(*, success=True, detail="done"):
    return AgentActionResult("write_ui_element", success, "ok", detail)


class RuntimeObservabilityTests(unittest.TestCase):
    def build(self, results, names=None, journal=None):
        self.events = []
        self.bus = MissionEventBus()
        self.bus.subscribe(None, self.events.append)
        self.raw_tools = FakeTools(results)
        self.tools = TracingToolRegistry(self.raw_tools, event_bus=self.bus, journal=journal)
        self.delegate = FakeRuntime(self.tools, names or ["write_ui_element"])
        return StructuredTracingRuntime(
            self.delegate, self.tools, journal=journal,
            configured_provider="cerebras", configured_model="configured-model",
        )

    def test_real_call_preserves_result_and_correlates_proof(self):
        result = action(detail=json.dumps({"verified": True, "value": "Hello", "value_length": 5}))
        runtime = self.build([result])
        phases = []
        turn = runtime.run("Hello", phase=phases.append)
        self.assertIs(turn, self.delegate.result)
        self.assertIs(turn.actions[0], result)
        self.assertEqual(self.raw_tools.calls, [("write_ui_element", {"text": "Hello"}, True)])
        self.assertEqual(phases, ["thinking", "acting"])
        kinds = [e.kind for e in self.events]
        self.assertEqual(kinds[0], "turn.started")
        self.assertEqual(kinds[-1], "turn.finished")
        request = next(e for e in self.events if e.kind == "tool.requested")
        response = next(e for e in self.events if e.kind == "tool.result")
        proof = next(e for e in self.events if e.kind == "proof")
        self.assertEqual(response.parent_event_id, request.event_id)
        self.assertEqual(proof.parent_event_id, request.event_id)
        self.assertEqual(proof.payload["result_event_id"], response.event_id)
        self.assertGreaterEqual(response.payload["duration_ms"], 0)
        self.assertNotIn("mission.completed", kinds)

    def test_success_without_observed_evidence_is_unverified(self):
        for detail in ("verified success", '{"verified":true}', '{"verified":true,"target":"editor"}',
                       '{"verified":"true","value":"hello"}', '{"verified":true,"proof":{}}'):
            with self.subTest(detail=detail):
                self.build([action(detail=detail)]).run("Hello")
                self.assertFalse(any(e.kind == "proof" for e in self.events))

    def test_failed_result_cannot_publish_proof(self):
        self.build([action(success=False, detail='{"verified":true,"value":"Hello"}')]).run("Hello")
        self.assertFalse(any(e.kind == "proof" for e in self.events))
        self.assertEqual(self.events[-1].payload["failed_action_count"], 1)

    def test_recovery_keeps_failed_action_and_only_verifies_later_result(self):
        self.build([
            action(success=False), action(detail='{"verified":true,"value":"Hello"}'),
        ], names=["first_attempt", "recovery_attempt"]).run("Hello")
        state = RuntimeActivityState()
        for event in self.events:
            state.apply(event)
        self.assertEqual([call.status for call in state.calls.values()], ["failed", "verified"])
        self.assertEqual(state.status, "finished")
        self.assertEqual(state.failed_action_count, 1)

    def test_no_action_turn_finishes_without_mission_or_proof_claim(self):
        runtime = self.build([])
        self.delegate.names = []
        runtime.run("Hello")
        self.assertEqual(self.events[-1].payload["action_count"], 0)
        self.assertFalse(any(e.kind in {"proof", "mission.completed"} for e in self.events))

    def test_exception_is_reported_and_original_exception_propagates(self):
        error = RuntimeError("Bearer private-token")
        runtime = self.build([error])
        with self.assertRaises(RuntimeError) as caught:
            runtime.run("Hello")
        self.assertIs(caught.exception, error)
        response = next(e for e in self.events if e.kind == "tool.result")
        self.assertFalse(response.success)
        self.assertEqual(self.events[-1].payload["outcome"], "error")
        self.assertNotIn("private-token", str([e.payload for e in self.events]))
        count = len(self.events)
        self.raw_tools.results.append(action())
        self.tools.execute("outside_turn", {})
        self.assertEqual(len(self.events), count)

    def test_failing_observer_does_not_stop_runtime(self):
        runtime = self.build([action()])
        self.bus.subscribe(None, lambda event: (_ for _ in ()).throw(RuntimeError("observer failed")))
        self.assertEqual(runtime.run("Hello").text, "done")
        self.assertEqual(len(self.raw_tools.calls), 1)

    def test_unavailable_journal_does_not_stop_runtime_or_events(self):
        class BrokenJournal:
            def create_mission(self, **kwargs):
                raise OSError("disk full")

            def append_event(self, **kwargs):
                raise OSError("disk full")

            def finish_mission(self, *args, **kwargs):
                raise OSError("disk full")

        runtime = self.build([action()], journal=BrokenJournal())
        self.assertEqual(runtime.run("Hello").text, "done")
        self.assertEqual(self.events[-1].kind, "turn.finished")

    def test_bus_and_journal_use_same_event_ids_and_redaction(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = StructuredEventJournal(Path(temp) / "trace.sqlite3")
            runtime = self.build([action()], journal=journal)
            runtime.run("password=private-value contact@example.com")
            trace = journal.mission_trace(self.events[0].mission_id)
            stored = {e["event_id"]: e for e in trace}
            for event in self.events:
                self.assertEqual(stored[event.event_id]["payload"], event.payload)
            self.assertNotIn("private-value", str(trace))
            self.assertNotIn("contact@example.com", str(trace))

    def test_redaction_covers_nested_free_text_secrets_and_bounds(self):
        secret = "gsk_" + "a" * 30
        payload = _safe_value({"api_key": "hidden", "detail": f"Bearer private-token {secret}",
                               "nested": {"text": 'password="private-value"'}, "large": "x" * 12000})
        self.assertNotIn("hidden", str(payload))
        self.assertNotIn("private-token", str(payload))
        self.assertNotIn(secret, str(payload))
        self.assertNotIn("private-value", str(payload))
        self.assertLessEqual(len(payload["large"]), 2401)

    def test_bound_method_observer_can_be_unsubscribed(self):
        class Observer:
            def observe(self, event):
                raise AssertionError("must be unsubscribed")

        observer = Observer()
        bus = MissionEventBus()
        bus.subscribe(None, observer.observe)
        bus.unsubscribe(None, observer.observe)
        self.assertEqual(bus.subscriber_counts()["*"], 0)
        self.assertEqual(bus.publish(BusEvent("test", "turn", {})), [])

    def test_thread_local_turn_ids_keep_tool_results_isolated(self):
        events = []
        bus = MissionEventBus()
        bus.subscribe(None, events.append)
        barrier = threading.Barrier(2)

        class Tools:
            def execute(self, name, arguments, *, approved=False):
                barrier.wait(timeout=3)
                return action()

        proxy = TracingToolRegistry(Tools(), event_bus=bus)

        def execute(turn_id):
            proxy.set_mission(turn_id)
            proxy.execute(turn_id, {})
            proxy.set_mission(None)

        threads = [threading.Thread(target=execute, args=(name,)) for name in ("turn-a", "turn-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        requests = {e.event_id: e for e in events if e.kind == "tool.requested"}
        results = [e for e in events if e.kind == "tool.result"]
        self.assertEqual(len(results), 2)
        for event in results:
            self.assertEqual(event.mission_id, requests[event.parent_event_id].mission_id)
            self.assertEqual(event.payload["tool_name"], event.mission_id)

    def test_builder_preserves_default_provider_without_observer(self):
        from jarvis_agent.agent_runtime import CerebrasResponsesAgent, build_agent_runtime

        configured = replace(settings, agent_provider="cerebras", structured_tracing_enabled=False,
                             runtime_observability_enabled=False)
        with patch("jarvis_agent.agent_runtime.settings", configured):
            self.assertIsInstance(build_agent_runtime(), CerebrasResponsesAgent)

    def test_regression_registry_selects_new_observation_pack(self):
        from jarvis_agent.regression_registry import DEFAULT_REGRESSION_REGISTRY

        selected = DEFAULT_REGRESSION_REGISTRY.select(changed_paths=["jarvis_agent/tracing_runtime.py"])
        self.assertIn("TEST-RUNTIME-OBSERVABILITY", {item.test_id for item in selected})

    def test_builder_observation_does_not_require_sqlite(self):
        from jarvis_agent.agent_runtime import CerebrasResponsesAgent, build_agent_runtime

        configured = replace(settings, agent_provider="cerebras", structured_tracing_enabled=False,
                             runtime_observability_enabled=True)
        with patch("jarvis_agent.agent_runtime.settings", configured):
            runtime = build_agent_runtime()
        self.assertIsInstance(runtime, StructuredTracingRuntime)
        self.assertIsInstance(runtime.delegate, CerebrasResponsesAgent)
        self.assertIsNone(runtime.journal)
        self.assertIsNotNone(runtime.event_bus)

    def test_builder_survives_journal_initialization_failure(self):
        from jarvis_agent.agent_runtime import build_agent_runtime

        configured = replace(settings, agent_provider="cerebras", structured_tracing_enabled=True,
                             runtime_observability_enabled=True)
        with patch("jarvis_agent.agent_runtime.settings", configured), patch(
            "jarvis_agent.event_journal.StructuredEventJournal", side_effect=OSError("disk full"),
        ):
            runtime = build_agent_runtime()
        self.assertIsNone(runtime.journal)
        self.assertIsNotNone(runtime.event_bus)


class RuntimeActivityTests(unittest.TestCase):
    def setUp(self):
        self.state = RuntimeActivityState(max_calls=2)
        self.state.apply(BusEvent("turn.started", "turn1", {"configured_provider": "cerebras"}))

    def request(self, request_id="request1"):
        return self.state.apply(BusEvent("tool.requested", "turn1", {"tool_name": "write_ui_element"},
                                       event_id=request_id))

    def response(self, success=True):
        return self.state.apply(BusEvent("tool.result", "turn1", {"duration_ms": 2.5},
                                       event_id="result1", parent_event_id="request1", success=success))

    def proof(self, **changes):
        payload = {"verified": True, "evidence": {"value": "Hello"},
                   "source": "tool_result", "result_event_id": "result1"}
        payload.update(changes)
        return self.state.apply(BusEvent("proof", "turn1", payload, event_id="proof1",
                                       parent_event_id="request1", success=True))

    def test_success_stays_unverified_until_correlated_proof(self):
        self.request()
        self.response()
        self.assertEqual(self.state.calls["request1"].status, "completed")
        self.assertFalse(self.proof(result_event_id="another_result"))
        self.assertFalse(self.proof(evidence={}))
        self.assertTrue(self.proof())
        self.assertEqual(self.state.calls["request1"].status, "verified")

    def test_failed_action_cannot_be_upgraded_by_proof(self):
        self.request()
        self.response(success=False)
        self.assertFalse(self.proof())
        self.assertEqual(self.state.calls["request1"].status, "failed")

    def test_unknown_or_old_events_do_not_change_current_turn(self):
        self.assertFalse(self.response())
        self.assertFalse(self.state.apply(BusEvent("tool.requested", "old_turn", {}, event_id="old")))
        self.assertEqual(len(self.state.calls), 0)

    def test_inspection_and_turn_completion_do_not_verify_action(self):
        self.request()
        self.response()
        self.state.apply(BusEvent("observation", "turn1", {"verified": True}))
        self.state.apply(BusEvent("mission.completed", "turn1", {}, success=True))
        self.state.apply(BusEvent("turn.finished", "turn1", {"outcome": "returned"}))
        self.assertEqual(self.state.status, "finished")
        self.assertEqual(self.state.calls["request1"].status, "completed")

    def test_bounded_history_and_new_turn_reset(self):
        for index in range(5):
            self.request(str(index))
        self.assertEqual(len(self.state.calls), 2)
        self.assertEqual(self.state.dropped_calls, 3)
        self.state.apply(BusEvent("turn.started", "turn2", {}))
        self.assertEqual(len(self.state.calls), 0)
        self.assertEqual(self.state.dropped_calls, 0)

    def test_duplicate_request_and_late_phase_do_not_reset_state(self):
        self.request()
        self.response()
        self.assertFalse(self.request())
        self.state.apply(BusEvent("turn.finished", "turn1", {"outcome": "returned"}))
        self.assertFalse(self.state.apply(BusEvent("runtime.phase", "turn1", {"phase": "acting"})))
        self.assertEqual(self.state.status, "finished")


class RuntimeActivityQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_real_events_cross_thread_and_display_distinct_proof(self):
        class Bridge(QObject):
            event = Signal(object)

        panel = RuntimeActivityPanel()
        bridge = Bridge()
        bridge.event.connect(panel.on_event, Qt.QueuedConnection)
        bus = MissionEventBus()
        bus.subscribe(None, bridge.event.emit)
        tools = TracingToolRegistry(FakeTools([
            action(), action(detail='{"verified":true,"value":"Hello"}'),
        ]), event_bus=bus)
        runtime = StructuredTracingRuntime(FakeRuntime(tools, ["first", "second"]), tools)
        thread = threading.Thread(target=lambda: runtime.run("Hello"))
        thread.start()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        deadline = time.monotonic() + 3
        while panel.state.status != "finished" and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertEqual(panel.calls.topLevelItemCount(), 2)
        self.assertIn("NON VÉRIFIÉ", panel.calls.topLevelItem(0).text(1))
        self.assertEqual(panel.calls.topLevelItem(1).text(1), "VÉRIFIÉ · PREUVE OUTIL")
        self.assertIn("critères de mission non évalués", panel.summary.text())
        panel.close()

    def test_existing_window_connects_worker_events_without_voice_or_network(self):
        from jarvis_agent.ui import JarvisWindow

        class Worker(QObject):
            state_changed = Signal(str)
            status_changed = Signal(str)
            transcript_changed = Signal(str)
            detail_changed = Signal(str)
            audio_level_changed = Signal(float)
            log_line = Signal(str)
            runtime_event = Signal(object)
            finished = Signal()

            @Slot()
            def run(self):
                bus = MissionEventBus()
                bus.subscribe(None, self.runtime_event.emit)
                tools = TracingToolRegistry(FakeTools([action()]), event_bus=bus)
                StructuredTracingRuntime(FakeRuntime(tools, ["write_ui_element"]), tools).run("Hello")
                self.finished.emit()

            def stop(self):
                pass

        configured = replace(settings, runtime_observability_enabled=True, ui_fullscreen=False)
        with patch("jarvis_agent.ui.AssistantWorker", Worker), patch("jarvis_agent.ui.settings", configured):
            window = JarvisWindow()
        window.show()
        deadline = time.monotonic() + 4
        while (window._thread.isRunning() or window._runtime_activity.state.status != "finished") and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertFalse(window._thread.isRunning())
        self.assertEqual(window._runtime_activity.calls.topLevelItemCount(), 1)
        self.assertIn("NON VÉRIFIÉ", window._runtime_activity.calls.topLevelItem(0).text(1))
        self.assertTrue(window.close())


if __name__ == "__main__":
    unittest.main()
