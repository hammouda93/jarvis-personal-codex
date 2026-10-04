from __future__ import annotations

import json
import unittest

from jarvis_agent.connector_gateway import ConnectorGateway, ConnectorResult
from jarvis_agent.connector_registry import (
    ConnectorBackend,
    DEFAULT_CONNECTOR_REGISTRY,
)
from jarvis_agent.connector_runtime import ConnectorToolRegistry
from jarvis_agent.live_kernel_gateway import RuntimeCapabilityResolver
from jarvis_agent.native_tools import AgentActionResult


class Delegate:
    def ollama_tools(self):
        return []

    def openai_tools(self):
        return []

    def requires_confirmation(self, name):
        return False

    def execute(self, name, arguments, *, approved=False):
        return AgentActionResult(name, True, "delegate")


class FakeAdapter:
    backend = ConnectorBackend.API

    def __init__(self, connector_id):
        self.connector_id = connector_id
        self.calls = []

    def execute(self, capability, arguments):
        self.calls.append((capability, dict(arguments)))
        return ConnectorResult(
            connector_id=self.connector_id,
            capability=capability,
            success=True,
            message="ok",
            data={"id": "fixture-123"},
        )


class ConnectorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ConnectorGateway(DEFAULT_CONNECTOR_REGISTRY)
        self.gmail = FakeAdapter("gmail")
        self.calendar = FakeAdapter("google_calendar")
        self.drive = FakeAdapter("google_drive")
        self.github = FakeAdapter("github")
        for adapter in (
            self.gmail,
            self.calendar,
            self.drive,
            self.github,
        ):
            self.gateway.register_adapter(adapter)
        self.tools = ConnectorToolRegistry(
            Delegate(),
            gateway=self.gateway,
            registry=DEFAULT_CONNECTOR_REGISTRY,
        )

    def test_registry_contains_calendar_drive_and_existing_domains(self):
        ids = {
            item.connector_id
            for item in DEFAULT_CONNECTOR_REGISTRY.all()
        }
        self.assertTrue(
            {"gmail", "google_calendar", "google_drive", "github"} <= ids
        )

    def test_list_connectors_reports_real_adapter_availability(self):
        result = self.tools.execute("list_connectors", {})
        self.assertTrue(result.success)
        payload = json.loads(result.detail)
        gmail = next(
            item for item in payload["connectors"]
            if item["id"] == "gmail"
        )
        self.assertTrue(gmail["connected"])
        self.assertEqual(gmail["backends"], ["api"])

    def test_read_tool_cannot_smuggle_send_capability(self):
        blocked = self.tools.execute(
            "connector_read",
            {
                "connector_id": "gmail",
                "capability": "send_message",
                "arguments": {},
            },
        )
        self.assertFalse(blocked.success)
        self.assertEqual(self.gmail.calls, [])
        self.assertEqual(
            json.loads(blocked.detail)["reason"],
            "connector_risk_boundary_mismatch",
        )

    def test_reversible_draft_does_not_require_external_tool(self):
        self.assertFalse(self.tools.requires_confirmation("connector_write"))
        result = self.tools.execute(
            "connector_write",
            {
                "connector_id": "gmail",
                "capability": "create_draft",
                "arguments": {"subject": "Fixture"},
            },
        )
        self.assertTrue(result.success)
        self.assertTrue(json.loads(result.detail)["verified"])

    def test_external_send_requires_confirmation_and_gateway_enforces_it(self):
        self.assertTrue(self.tools.requires_confirmation("connector_external"))
        blocked = self.tools.execute(
            "connector_external",
            {
                "connector_id": "gmail",
                "capability": "send_message",
                "arguments": {"to": "fixture@example.com"},
            },
            approved=False,
        )
        self.assertFalse(blocked.success)
        self.assertEqual(self.gmail.calls, [])

        allowed = self.tools.execute(
            "connector_external",
            {
                "connector_id": "gmail",
                "capability": "send_message",
                "arguments": {"to": "fixture@example.com"},
            },
            approved=True,
        )
        self.assertTrue(allowed.success)
        self.assertEqual(self.gmail.calls[-1][0], "send_message")

    def test_provider_success_without_structured_data_is_not_verified(self):
        class EmptyAdapter(FakeAdapter):
            def execute(self, capability, arguments):
                return ConnectorResult(
                    connector_id=self.connector_id,
                    capability=capability,
                    success=True,
                    message="accepted",
                    data={},
                )

        gateway = ConnectorGateway(DEFAULT_CONNECTOR_REGISTRY)
        gateway.register_adapter(EmptyAdapter("gmail"))
        tools = ConnectorToolRegistry(Delegate(), gateway=gateway)
        result = tools.execute(
            "connector_write",
            {
                "connector_id": "gmail",
                "capability": "create_draft",
            },
        )
        self.assertTrue(result.success)
        self.assertFalse(json.loads(result.detail)["verified"])

    def test_live_kernel_routes_connector_by_domain_and_risk(self):
        resolver = RuntimeCapabilityResolver()

        gmail = resolver.resolve(
            "connector_external",
            {"connector_id": "gmail"},
        )
        self.assertEqual(gmail.agent_id, "communications")
        self.assertEqual(gmail.capability, "communications.send")

        calendar = resolver.resolve(
            "connector_external",
            {"connector_id": "google_calendar"},
        )
        self.assertEqual(calendar.agent_id, "personal_admin")
        self.assertEqual(calendar.capability, "personal_admin.write")

        drive = resolver.resolve(
            "connector_write",
            {"connector_id": "google_drive"},
        )
        self.assertEqual(drive.agent_id, "data")
        self.assertEqual(drive.capability, "data.write")

        github = resolver.resolve(
            "connector_external",
            {"connector_id": "github"},
        )
        self.assertEqual(github.agent_id, "developer")
        self.assertEqual(github.capability, "developer.publish")


if __name__ == "__main__":
    unittest.main()
