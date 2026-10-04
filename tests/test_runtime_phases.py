from __future__ import annotations

import unittest

from jarvis_agent.agent_runtime import (
    _recovery_phase_from_result,
    _tool_runtime_phase,
)
from jarvis_agent.native_tools import AgentActionResult


class RuntimePhaseTests(unittest.TestCase):
    def test_explicit_research_has_no_autonomous_announcement_phase(self):
        phase = _tool_runtime_phase(
            "research_web",
            "Recherche la documentation AppUserModelID sur Internet",
            [],
        )
        self.assertEqual(phase, "researching_explicit")

    def test_autonomous_research_after_local_failure_is_distinct(self):
        actions = [
            AgentActionResult(
                name="open_application",
                success=False,
                message="not found",
            )
        ]
        phase = _tool_runtime_phase(
            "research_web",
            "Ouvre mon application interne",
            actions,
        )
        self.assertEqual(
            phase,
            "researching_autonomous_after_failure",
        )

    def test_autonomous_external_research_is_distinct_without_local_failure(self):
        phase = _tool_runtime_phase(
            "research_web",
            "Quel est le statut actuel de ce produit ?",
            [],
        )
        self.assertEqual(
            phase,
            "researching_autonomous_external",
        )

    def test_observation_after_unverified_mutation_is_verifying(self):
        actions = [
            AgentActionResult(
                name="write_ui_element",
                success=True,
                message="typed",
                detail='{"verified": false}',
            )
        ]
        self.assertEqual(
            _tool_runtime_phase(
                "inspect_active_window",
                "écris bonjour",
                actions,
            ),
            "verifying",
        )

    def test_normal_inspection_is_observing(self):
        self.assertEqual(
            _tool_runtime_phase(
                "inspect_active_window",
                "qu'est-ce qui est ouvert ?",
                [],
            ),
            "observing",
        )

    def test_recovery_guard_budget_becomes_blocked(self):
        result = AgentActionResult(
            name="click_ui_element",
            success=False,
            message="stop",
            detail=(
                '{"recovery_guard":true,'
                '"reason":"turn_tool_budget_exhausted"}'
            ),
        )
        self.assertEqual(
            _recovery_phase_from_result(result),
            "blocked",
        )

    def test_recovery_guard_reinspection_requirement_is_recovering(self):
        result = AgentActionResult(
            name="click_ui_element",
            success=False,
            message="observe",
            detail=(
                '{"recovery_guard":true,'
                '"reason":"fresh_observation_required"}'
            ),
        )
        self.assertEqual(
            _recovery_phase_from_result(result),
            "recovering",
        )


if __name__ == "__main__":
    unittest.main()
