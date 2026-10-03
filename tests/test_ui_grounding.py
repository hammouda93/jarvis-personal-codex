from __future__ import annotations

import unittest

from jarvis_agent.ui_grounding import ground_role


def snapshot(controls):
    return {
        "window": {
            "title": "Fixture App",
            "bounds": [0, 0, 1200, 800],
        },
        "controls": controls,
    }


class UIGroundingTests(unittest.TestCase):
    def test_search_input_and_message_composer_are_distinguished_by_semantics(self):
        data = snapshot(
            [
                {
                    "ref": "e1",
                    "type": "Edit",
                    "enabled": True,
                    "writable": True,
                    "name": "Search",
                    "bounds": [20, 60, 500, 110],
                },
                {
                    "ref": "e2",
                    "type": "Edit",
                    "enabled": True,
                    "writable": True,
                    "label_hint": "Type a message",
                    "bounds": [220, 700, 1000, 770],
                },
            ]
        )
        search = ground_role(data, "search_input")
        composer = ground_role(data, "message_composer")
        self.assertEqual(search.status, "resolved")
        self.assertEqual(search.selected.ref, "e1")
        self.assertEqual(composer.status, "resolved")
        self.assertEqual(composer.selected.ref, "e2")

    def test_send_button_requires_semantic_evidence(self):
        data = snapshot(
            [
                {
                    "ref": "e4",
                    "type": "Button",
                    "enabled": True,
                    "name": "Emoji",
                    "bounds": [1040, 700, 1090, 750],
                },
                {
                    "ref": "e5",
                    "type": "Button",
                    "enabled": True,
                    "name": "Send",
                    "bounds": [1100, 700, 1170, 750],
                },
            ]
        )
        result = ground_role(data, "send_button")
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.selected.ref, "e5")

    def test_two_equally_plausible_confirm_buttons_are_ambiguous(self):
        data = snapshot(
            [
                {
                    "ref": "e1",
                    "type": "Button",
                    "enabled": True,
                    "name": "Confirm",
                    "bounds": [700, 650, 800, 700],
                },
                {
                    "ref": "e2",
                    "type": "Button",
                    "enabled": True,
                    "name": "Confirm changes",
                    "bounds": [820, 650, 980, 700],
                },
            ]
        )
        result = ground_role(data, "dialog_confirm_button")
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.selected)

    def test_result_item_uses_mission_entity_hint_without_app_rule(self):
        data = snapshot(
            [
                {
                    "ref": "e8",
                    "type": "ListItem",
                    "enabled": True,
                    "name": "Chaima Ben Ali",
                    "bounds": [250, 180, 950, 230],
                },
                {
                    "ref": "e9",
                    "type": "ListItem",
                    "enabled": True,
                    "name": "Sami",
                    "bounds": [250, 235, 950, 285],
                },
            ]
        )
        result = ground_role(
            data,
            "result_item",
            mission_hint="Chaima",
        )
        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.selected.ref, "e8")

    def test_unlabelled_message_fields_are_not_guessed(self):
        data = snapshot(
            [
                {
                    "ref": "e1",
                    "type": "Edit",
                    "enabled": True,
                    "writable": True,
                    "bounds": [100, 650, 500, 720],
                },
                {
                    "ref": "e2",
                    "type": "Edit",
                    "enabled": True,
                    "writable": True,
                    "bounds": [550, 650, 1000, 720],
                },
            ]
        )
        result = ground_role(data, "message_composer")
        self.assertIn(result.status, {"not_found", "ambiguous"})
        self.assertIsNone(result.selected)

    def test_disabled_control_is_never_grounded(self):
        data = snapshot(
            [
                {
                    "ref": "e1",
                    "type": "Button",
                    "enabled": False,
                    "name": "Send",
                    "bounds": [1000, 700, 1100, 760],
                }
            ]
        )
        result = ground_role(data, "send_button")
        self.assertEqual(result.status, "not_found")

    def test_invalid_role_is_explicit(self):
        result = ground_role(snapshot([]), "whatsapp_magic_field")
        self.assertEqual(result.status, "invalid_role")


if __name__ == "__main__":
    unittest.main()
