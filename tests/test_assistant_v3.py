import unittest
from dataclasses import replace
from unittest.mock import patch

from jarvis_agent.assistant_v3 import AssistantWorker
from jarvis_agent.config import settings
from jarvis_agent.tools import ToolIntent


class AssistantV3FastPathTests(unittest.TestCase):
    def test_semantic_missions_do_not_allow_voice_shortcut_to_bypass_native_path(self):
        with patch("jarvis_agent.assistant_v3.settings", replace(settings, semantic_missions_enabled=True)), \
                patch("jarvis_agent.assistant_v3.execute") as direct_execute:
            handled = AssistantWorker._handle_simple_direct_action(
                None, "Ouvre Chrome.", ToolIntent("app.open", {"app": "chrome"}),
            )
        self.assertFalse(handled)
        direct_execute.assert_not_called()

    def test_simple_youtube_open_uses_direct_path(self):
        self.assertTrue(
            AssistantWorker._is_simple_direct_action(
                "Ouvre YouTube.",
                ToolIntent("browser.open_url", {"url": "https://www.youtube.com"}),
            )
        )

    def test_simple_chrome_open_uses_direct_path(self):
        self.assertTrue(
            AssistantWorker._is_simple_direct_action(
                "Ouvre Chrome.",
                ToolIntent("app.open", {"app": "chrome"}),
            )
        )

    def test_in_app_search_stays_with_agent(self):
        self.assertFalse(
            AssistantWorker._is_simple_direct_action(
                "Recherche dans la barre de recherche YouTube sur le sport.",
                ToolIntent(
                    "browser.search",
                    {"query": "dans la barre de recherche youtube sur le sport"},
                ),
            )
        )

    def test_in_app_video_selection_stays_with_agent(self):
        self.assertFalse(
            AssistantWorker._is_simple_direct_action(
                "Ouvre la première vidéo pertinente dans l'onglet YouTube.",
                ToolIntent(
                    "browser.open_url",
                    {"url": "https://www.youtube.com"},
                ),
            )
        )

    def test_installer_request_stays_with_agent(self):
        self.assertFalse(
            AssistantWorker._is_simple_direct_action(
                "Ouvre-moi le fichier d'installation de Cursor maintenant.",
                ToolIntent("app.open", {"app": "cursor"}),
            )
        )

    def test_compound_command_stays_with_agent(self):
        self.assertFalse(
            AssistantWorker._is_simple_direct_action(
                "Ouvre Chrome et recherche les agents IA.",
                ToolIntent("app.open", {"app": "chrome"}),
            )
        )


if __name__ == "__main__":
    unittest.main()
