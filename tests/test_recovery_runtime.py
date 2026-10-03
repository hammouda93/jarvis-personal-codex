from __future__ import annotations

import json
import unittest

from jarvis_agent.native_tools import AgentActionResult
from jarvis_agent.recovery_runtime import RecoveryToolRegistry


class FakeTools:
    runtime_instructions = "delegate instructions"

    def __init__(self):
        self.calls = []
        self.responses = []

    def ollama_tools(self):
        return [{"type": "function", "function": {"name": "x"}}]

    def openai_tools(self):
        return [{"type": "function", "name": "x"}]

    def requires_confirmation(self, name):
        return name == "danger"

    def execute(self, name, arguments, *, approved=False):
        self.calls.append((name, dict(arguments or {}), approved))
        if self.responses:
            return self.responses.pop(0)
        return AgentActionResult(name=name, success=True, message="ok")


class RecoveryToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.delegate = FakeTools()
        self.guard = RecoveryToolRegistry(
            self.delegate,
            max_total_calls=5,
            max_consecutive_failures=3,
            max_same_tool_calls=3,
        )
        self.guard.begin_turn("test")

    def test_identical_failed_call_is_blocked_without_reexecuting(self):
        self.delegate.responses = [
            AgentActionResult(
                name="open_application",
                success=False,
                message="missing",
            )
        ]
        first = self.guard.execute(
            "open_application",
            {"name": "Future App"},
        )
        second = self.guard.execute(
            "open_application",
            {"name": "Future App"},
        )
        self.assertFalse(first.success)
        self.assertFalse(second.success)
        self.assertEqual(len(self.delegate.calls), 1)
        detail = json.loads(second.detail)
        self.assertEqual(
            detail["reason"],
            "identical_failed_call_blocked",
        )

    def test_different_arguments_are_not_identical_retry(self):
        self.delegate.responses = [
            AgentActionResult(
                name="open_application",
                success=False,
                message="missing",
            ),
            AgentActionResult(
                name="open_application",
                success=True,
                message="opened",
            ),
        ]
        self.guard.execute("open_application", {"name": "A"})
        second = self.guard.execute("open_application", {"name": "B"})
        self.assertTrue(second.success)
        self.assertEqual(len(self.delegate.calls), 2)

    def test_failed_ui_mutation_requires_fresh_observation(self):
        self.delegate.responses = [
            AgentActionResult(
                name="click_ui_element",
                success=False,
                message="stale",
            ),
            AgentActionResult(
                name="inspect_active_window",
                success=True,
                message="observed",
            ),
            AgentActionResult(
                name="click_ui_element",
                success=True,
                message="clicked",
                detail='{"verified": true}',
            ),
        ]
        self.guard.execute("click_ui_element", {"ref": "e1"})
        blocked = self.guard.execute(
            "click_ui_element",
            {"ref": "e2"},
        )
        self.assertFalse(blocked.success)
        self.assertEqual(
            json.loads(blocked.detail)["reason"],
            "fresh_observation_required",
        )
        observed = self.guard.execute("inspect_active_window", {})
        self.assertTrue(observed.success)
        retried = self.guard.execute(
            "click_ui_element",
            {"ref": "e2"},
        )
        self.assertTrue(retried.success)
        self.assertEqual(len(self.delegate.calls), 3)

    def test_successful_unverified_ui_mutation_also_requires_observation(self):
        self.delegate.responses = [
            AgentActionResult(
                name="write_ui_element",
                success=True,
                message="typed",
                detail='{"verified": false}',
            ),
            AgentActionResult(
                name="inspect_active_window",
                success=True,
                message="observed",
            ),
        ]
        self.assertTrue(
            self.guard.execute(
                "write_ui_element",
                {"ref": "e1", "text": "hello"},
            ).success
        )
        blocked = self.guard.execute(
            "press_key",
            {"key": "ENTER"},
        )
        self.assertFalse(blocked.success)
        self.assertEqual(
            json.loads(blocked.detail)["reason"],
            "fresh_observation_required",
        )

    def test_verified_ui_mutation_does_not_force_extra_observation(self):
        self.delegate.responses = [
            AgentActionResult(
                name="write_ui_element",
                success=True,
                message="typed",
                detail='{"verified": true, "proof": {"value": "hello"}}',
            ),
            AgentActionResult(
                name="press_key",
                success=True,
                message="pressed",
            ),
        ]
        self.guard.execute(
            "write_ui_element",
            {"ref": "e1", "text": "hello"},
        )
        result = self.guard.execute("press_key", {"key": "ENTER"})
        self.assertTrue(result.success)

    def test_total_budget_stops_without_delegate_call(self):
        for index in range(5):
            self.guard.execute(
                "get_current_time",
                {"index": index},
            )
        blocked = self.guard.execute(
            "get_current_time",
            {"index": 99},
        )
        self.assertFalse(blocked.success)
        self.assertEqual(len(self.delegate.calls), 5)
        self.assertEqual(
            json.loads(blocked.detail)["reason"],
            "turn_tool_budget_exhausted",
        )

    def test_turn_reset_clears_failure_signature(self):
        self.delegate.responses = [
            AgentActionResult(
                name="open_application",
                success=False,
                message="missing",
            ),
            AgentActionResult(
                name="open_application",
                success=True,
                message="now installed",
            ),
        ]
        self.guard.execute("open_application", {"name": "A"})
        self.guard.begin_turn("new turn")
        result = self.guard.execute(
            "open_application",
            {"name": "A"},
        )
        self.assertTrue(result.success)

    def test_registry_contract_is_proxied(self):
        self.assertTrue(self.guard.ollama_tools())
        self.assertTrue(self.guard.openai_tools())
        self.assertTrue(self.guard.requires_confirmation("danger"))
        self.assertIn("Recovery boundary", self.guard.runtime_instructions)


if __name__ == "__main__":
    unittest.main()
