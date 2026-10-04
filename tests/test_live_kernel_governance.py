from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis_agent.capability_registry import DEFAULT_CAPABILITY_REGISTRY
from jarvis_agent.live_kernel_gateway import (
    KernelGovernedToolRegistry,
    RuntimeCapabilityResolver,
)
from jarvis_agent.native_tools import AgentActionResult
from jarvis_agent.live_kernel_scheduler import LiveKernelScheduler
from jarvis_agent.kernel_contracts import SyscallStatus


class FakeTools:
    def __init__(self):
        self.calls = []

    def ollama_tools(self):
        return []

    def openai_tools(self):
        return []

    def requires_confirmation(self, name):
        return False

    def execute(self, name, arguments, *, approved=False):
        self.calls.append((name, dict(arguments or {}), approved))
        return AgentActionResult(
            name=name,
            success=True,
            message="ok",
            detail='{"verified":true,"proof":{"fixture":true}}',
        )


class LiveKernelGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.delegate = FakeTools()
        self.registry = KernelGovernedToolRegistry(self.delegate)
        self.registry.begin_turn("fixture")

    def test_every_current_native_tool_has_a_live_capability_route(self):
        from jarvis_agent.native_tools import NativeToolRegistry

        resolver = RuntimeCapabilityResolver()
        names = [
            item["function"]["name"]
            for item in NativeToolRegistry().ollama_tools()
        ]
        missing = [name for name in names if resolver.resolve(name) is None]
        self.assertEqual(missing, [])

    def test_research_is_read_scoped_to_research_agent(self):
        route = RuntimeCapabilityResolver().resolve("research_web")
        self.assertEqual(route.agent_id, "research")
        self.assertEqual(route.capability, "research.web")
        registered = DEFAULT_CAPABILITY_REGISTRY.get_capability(route.capability)
        self.assertEqual(registered.provider_agent_id, "research")

    def test_authorized_tool_executes_through_manifest(self):
        result = self.registry.execute("inspect_active_window", {})
        self.assertTrue(result.success)
        self.assertEqual(self.delegate.calls[0][0], "inspect_active_window")

    def test_unmapped_tool_fails_closed(self):
        result = self.registry.execute("invented_hidden_tool", {})
        self.assertFalse(result.success)
        self.assertEqual(self.delegate.calls, [])
        self.assertEqual(
            json.loads(result.detail)["reason"], "unmapped_live_tool"
        )

    def test_external_side_effect_requires_approval(self):
        self.assertTrue(
            self.registry.requires_confirmation("msf_commit_mutation")
        )
        blocked = self.registry.execute(
            "msf_commit_mutation",
            {"preview_id": "p1"},
            approved=False,
        )
        self.assertFalse(blocked.success)
        self.assertEqual(self.delegate.calls, [])
        self.assertTrue(json.loads(blocked.detail)["approval_required"])

        allowed = self.registry.execute(
            "msf_commit_mutation",
            {"preview_id": "p1"},
            approved=True,
        )
        self.assertTrue(allowed.success)
        self.assertTrue(self.delegate.calls[0][2])

    def test_authorized_tool_flows_through_durable_scheduler(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = LiveKernelScheduler(base_dir=Path(tmp))
            registry = KernelGovernedToolRegistry(
                self.delegate,
                scheduler=scheduler,
            )
            registry.begin_turn("observe")
            result = registry.execute("inspect_active_window", {})
            self.assertTrue(result.success)
            rows = scheduler.store.for_mission(
                registry._turn().mission_id
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], SyscallStatus.SUCCEEDED)
            self.assertEqual(scheduler.snapshot()["active_total"], 0)

    def test_tool_is_scoped_to_declared_agent_manifest(self):
        route = RuntimeCapabilityResolver().resolve("write_ui_element")
        self.assertEqual(route.agent_id, "windows")
        self.assertIn(
            "write_ui_element",
            DEFAULT_CAPABILITY_REGISTRY.get_agent("windows").allowed_tools,
        )


if __name__ == "__main__":
    unittest.main()
